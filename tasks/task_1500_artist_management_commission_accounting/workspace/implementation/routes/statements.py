"""Statement endpoints (PRD 3.8)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ARTIST_ARCHIVED,
    ERR_STATEMENT_PERIOD_FUTURE,
    ERR_STATEMENT_PERIOD_OVERLAP,
    ERR_PRIOR_STATEMENT_OPEN,
    ERR_DISPUTE_NOT_RESOLVED,
)
from response import success_object, success_list
from routes.helpers import get_one, list_response, public, scoped_mutation_auth, get_pagination
from services.calculations import generate_statement_lines, recompute_statement_totals
from services.core import new_record, touch, recompute_artist
from middleware import get_caller, check_role_allowed, resolve_entity_backed, check_artist_scope, check_team_active
from routes.helpers import ALL_READ_ROLES
from util import CLOCK, parse_date
from validate import (
    get_body, req_date, req_enum, req_str, require_path_resource, require_ref,
)

bp = Blueprint("statements", __name__)

BASES = {"ACCRUAL", "CASH"}
DISPUTE_WINDOW_DAYS = 30


@bp.post("/statements/generate")
def generate_statement():
    body = get_body()
    artist_id = req_str(body, "artist_id")
    caller = scoped_mutation_auth(["BusinessManager"], body_artist_id=artist_id)
    p_start = req_date(body, "period_start_date")
    p_end = req_date(body, "period_end_date")
    basis = req_enum(body, "basis", BASES)

    if parse_date(p_end) < parse_date(p_start):
        raise_error(ERR_INVALID_REQUEST, "period_end_date must be on or after period_start_date")

    artist = require_ref("artists", artist_id, "artist_id")

    # Priority 12: archived artist
    if artist["status"] == "ARCHIVED":
        raise_error(ERR_ARTIST_ARCHIVED, "artist is ARCHIVED")
    # Priority 11: period not in the future
    if parse_date(p_end) > CLOCK.today():
        raise_error(ERR_STATEMENT_PERIOD_FUTURE, "period_end_date is after the logical clock date")

    new_start = parse_date(p_start)
    new_end = parse_date(p_end)

    # Priority 13: closed-interval overlap with any non-DISCARDED statement
    for s in db["statements"].values():
        if s["artist_id"] != artist_id or s["status"] == "DISCARDED":
            continue
        s_start = parse_date(s["period_start_date"])
        s_end = parse_date(s["period_end_date"])
        if new_start <= s_end and s_start <= new_end:
            raise_error(ERR_STATEMENT_PERIOD_OVERLAP,
                        "statement period collides with an existing non-DISCARDED statement")

    # Priority 12: immediately preceding statement must not be DRAFT
    prior = None
    for s in db["statements"].values():
        if s["artist_id"] != artist_id or s["status"] == "DISCARDED":
            continue
        if parse_date(s["period_end_date"]) < new_start:
            if prior is None or parse_date(s["period_end_date"]) > parse_date(prior["period_end_date"]):
                prior = s
    if prior is not None and prior["status"] == "DRAFT":
        raise_error(ERR_PRIOR_STATEMENT_OPEN,
                    "the immediately preceding statement is still DRAFT")

    carry_in = prior["carry_out_cents"] if prior is not None else 0

    rec = new_record("statements", {
        "artist_id": artist_id,
        "prior_statement_id": prior["id"] if prior else None,
        "period_start_date": p_start,
        "period_end_date": p_end,
        "basis": basis,
        "revision_number": 1,
        "status": "DRAFT",
        "issued_at": None,
        "dispute_window_ends_at": None,
        "rate_snapshot": [],
        "gross_total_cents": 0,
        "commission_total_cents": 0,
        "income_net_total_cents": 0,
        "expense_total_cents": 0,
        "recoup_total_cents": 0,
        "adjustment_total_cents": 0,
        "carry_in_cents": carry_in,
        "net_payable_cents": 0,
        "disbursed_cents": 0,
        "carry_out_cents": 0,
    })
    generate_statement_lines(rec)
    recompute_statement_totals(rec)
    return success_object(public(rec), status=201)


@bp.get("/statements/<rid>")
def get_statement(rid):
    return get_one("statements", rid)


@bp.get("/statements")
def list_statements():
    filters = {
        "artist_id": request.args.get("artist_id"),
        "prior_statement_id": request.args.get("prior_statement_id"),
        "status": request.args.get("status"),
        "basis": request.args.get("basis"),
    }
    return list_response("statements", filters)


@bp.get("/statements/<rid>/lines")
def list_statement_lines(rid):
    caller = get_caller()
    check_role_allowed(caller, ALL_READ_ROLES)
    resolve_entity_backed(caller)
    stmt = require_path_resource("statements", rid)
    check_artist_scope(caller, stmt["artist_id"])
    check_team_active(caller)

    lines = [l for l in db["statement_lines"].values() if l["statement_id"] == rid]
    lines.sort(key=lambda l: (l["created_at"], l["id"]))
    total = len(lines)
    limit, offset = get_pagination()
    page = lines[offset:offset + limit]
    return success_list([public(l) for l in page], total, limit, offset)


@bp.post("/statements/<rid>/issue")
def issue_statement(rid):
    caller = scoped_mutation_auth(["BusinessManager"], "statements", rid)
    stmt = require_path_resource("statements", rid)
    if stmt["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "issue requires DRAFT")
    stmt["status"] = "ISSUED"
    stmt["issued_at"] = CLOCK.now_iso()
    stmt["dispute_window_ends_at"] = (CLOCK.now() + timedelta(days=DISPUTE_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    touch(stmt)

    # Issue sweep: income events -> POSTED; expenses -> REIMBURSED; recoup events pinned
    for eid in stmt.pop("_swept_income_event_ids", []) or []:
        ev = db["income_events"].get(eid)
        if ev is not None and ev["status"] in ("VERIFIED", "SETTLED"):
            ev["status"] = "POSTED"
            ev["statement_id"] = stmt["id"]
            touch(ev)
    for eid in stmt.pop("_swept_expense_ids", []) or []:
        exp = db["expenses"].get(eid)
        if exp is not None and exp["status"] == "APPROVED":
            exp["status"] = "REIMBURSED"
            exp["reimbursed_statement_id"] = stmt["id"]
            touch(exp)
    for eid in stmt.pop("_swept_recoup_event_ids", []) or []:
        ev = db["income_events"].get(eid)
        if ev is not None and ev["recoup_statement_id"] is None:
            ev["recoup_statement_id"] = stmt["id"]
            touch(ev)
    return success_object(public(stmt))


@bp.post("/statements/<rid>/acknowledge")
def acknowledge_statement(rid):
    caller = scoped_mutation_auth(["Artist"], "statements", rid)
    stmt = require_path_resource("statements", rid)
    if stmt["status"] != "ISSUED":
        raise_error(ERR_INVALID_STATE, "acknowledge requires ISSUED")
    stmt["status"] = "ACKNOWLEDGED"
    touch(stmt)
    return success_object(public(stmt))


@bp.post("/statements/<rid>/amend")
def amend_statement(rid):
    caller = scoped_mutation_auth(["BusinessManager"], "statements", rid)
    stmt = require_path_resource("statements", rid)
    if stmt["status"] != "DISPUTED":
        raise_error(ERR_INVALID_STATE, "amend requires DISPUTED")
    # All disputes on this statement must be resolved
    for d in db["disputes"].values():
        if d["statement_id"] == stmt["id"] and d["status"] in ("OPEN", "UNDER_REVIEW", "ESCALATED"):
            raise_error(ERR_DISPUTE_NOT_RESOLVED,
                        "a dispute on this statement is still open, under review, or escalated")
    # Hop 1: append ADJUSTMENT lines for upheld disputes not yet applied
    for d in sorted(
        [d for d in db["disputes"].values()
         if d["statement_id"] == stmt["id"] and d["status"] == "RESOLVED_UPHELD"],
        key=lambda d: (d["created_at"], d["id"]),
    ):
        already = any(
            l for l in db["statement_lines"].values()
            if l["statement_id"] == stmt["id"] and l["line_type"] == "ADJUSTMENT" and l["ref_id"] == d["id"]
        )
        if already:
            continue
        new_record("statement_lines", {
            "statement_id": stmt["id"],
            "line_type": "ADJUSTMENT",
            "ref_id": d["id"],
            "amount_cents": d["awarded_amount_cents"],
            "commission_cents": 0,
            "note": f"Dispute {d['id']} upheld award",
        }, with_version=False)
    stmt["revision_number"] = stmt.get("revision_number", 1) + 1
    # Hop 2: totals re-run over the amended line set
    recompute_statement_totals(stmt)
    # Back to ISSUED with a fresh dispute window
    stmt["status"] = "ISSUED"
    stmt["issued_at"] = CLOCK.now_iso()
    stmt["dispute_window_ends_at"] = (CLOCK.now() + timedelta(days=DISPUTE_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    touch(stmt)
    # Hop 3: artist version increments; lifetime aggregates NOT restated
    artist = db["artists"].get(stmt["artist_id"])
    if artist is not None:
        touch(artist)
    return success_object(public(stmt))


@bp.post("/statements/<rid>/disburse")
def disburse_statement(rid):
    caller = scoped_mutation_auth(["BusinessManager"], "statements", rid)
    stmt = require_path_resource("statements", rid)
    if stmt["status"] != "ACKNOWLEDGED":
        raise_error(ERR_INVALID_STATE, "disburse requires ACKNOWLEDGED")
    stmt["status"] = "FINALIZED"
    touch(stmt)
    recompute_artist(stmt["artist_id"], bump=True)
    return success_object(public(stmt))


@bp.post("/statements/<rid>/discard")
def discard_statement(rid):
    caller = scoped_mutation_auth(["BusinessManager"], "statements", rid)
    stmt = require_path_resource("statements", rid)
    if stmt["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "discard requires DRAFT")
    stmt["status"] = "DISCARDED"
    touch(stmt)
    return success_object(public(stmt))
