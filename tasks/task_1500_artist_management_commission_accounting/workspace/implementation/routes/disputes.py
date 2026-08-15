"""Dispute endpoints (PRD 3.9)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_DISPUTE_WINDOW_CLOSED,
    ERR_DISPUTE_ALREADY_ACTIVE,
)
from response import success_object
from routes.helpers import get_one, list_response, public, scoped_mutation_auth
from services.core import new_record, touch, has_active_dispute
from validate import (
    get_body, opt_int, opt_str, req_enum, req_int, req_str,
    require_path_resource, require_ref,
)

bp = Blueprint("disputes", __name__)

REASONS = {"COMMISSION_RATE", "INCOME_MISSING", "EXPENSE_UNAUTHORIZED",
           "RECOUPMENT_ERROR", "SUNSET_MISCLASSIFIED", "OTHER"}
OUTCOMES = {"UPHELD", "REJECTED"}


@bp.post("/disputes")
def create_dispute():
    body = get_body()
    artist_id = req_str(body, "artist_id")
    caller = scoped_mutation_auth(["Artist"], body_artist_id=artist_id)
    statement_id = req_str(body, "statement_id")
    reason = req_enum(body, "reason", REASONS)
    claimed = req_int(body, "claimed_amount_cents", positive=True)

    require_ref("artists", artist_id, "artist_id")
    stmt = require_ref("statements", statement_id, "statement_id")

    if stmt["status"] in ("DRAFT", "DISCARDED"):
        raise_error(ERR_INVALID_STATE, f"cannot dispute a {stmt['status']} statement")
    if stmt["status"] in ("ACKNOWLEDGED", "FINALIZED"):
        raise_error(ERR_DISPUTE_WINDOW_CLOSED, "the dispute window has closed")
    if stmt["status"] == "DISPUTED":
        raise_error(ERR_DISPUTE_ALREADY_ACTIVE, "another dispute is already active")

    rec = new_record("disputes", {
        "artist_id": artist_id,
        "statement_id": statement_id,
        "reason": reason,
        "claimed_amount_cents": claimed,
        "status": "OPEN",
        "awarded_amount_cents": None,
        "resolution_note": None,
    })
    stmt["status"] = "DISPUTED"
    touch(stmt)
    return success_object(public(rec), status=201)


@bp.get("/disputes/<rid>")
def get_dispute(rid):
    return get_one("disputes", rid)


@bp.get("/disputes")
def list_disputes():
    filters = {
        "artist_id": request.args.get("artist_id"),
        "statement_id": request.args.get("statement_id"),
        "status": request.args.get("status"),
    }
    return list_response("disputes", filters)


@bp.post("/disputes/<rid>/start-review")
def start_review(rid):
    caller = scoped_mutation_auth(["BusinessManager"], "disputes", rid)
    d = require_path_resource("disputes", rid)
    if d["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "start-review requires OPEN")
    d["status"] = "UNDER_REVIEW"
    touch(d)
    return success_object(public(d))


@bp.post("/disputes/<rid>/resolve")
def resolve_dispute(rid):
    caller = scoped_mutation_auth(["BusinessManager", "FirmAdmin"], "disputes", rid)
    body = get_body()
    d = require_path_resource("disputes", rid)
    outcome = req_enum(body, "outcome", OUTCOMES)
    awarded = opt_int(body, "awarded_amount_cents")
    resolution_note = opt_str(body, "resolution_note")

    if d["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "resolve requires UNDER_REVIEW")
    if outcome == "UPHELD":
        if awarded is None or awarded <= 0:
            raise_error(ERR_INVALID_REQUEST,
                        "RESOLVED_UPHELD requires awarded_amount_cents > 0")
        d["awarded_amount_cents"] = awarded
        d["status"] = "RESOLVED_UPHELD"
    else:
        d["status"] = "RESOLVED_REJECTED"
    d["resolution_note"] = resolution_note
    touch(d)
    return success_object(public(d))


@bp.post("/disputes/<rid>/withdraw")
def withdraw_dispute(rid):
    caller = scoped_mutation_auth(["Artist"], "disputes", rid)
    d = require_path_resource("disputes", rid)
    if d["status"] not in ("OPEN", "UNDER_REVIEW"):
        raise_error(ERR_INVALID_STATE, f"cannot withdraw from {d['status']}")
    d["status"] = "WITHDRAWN"
    touch(d)
    # Compensation revert: no other active dispute -> statement DISPUTED -> ISSUED
    stmt = db["statements"].get(d["statement_id"])
    if stmt is not None and stmt["status"] == "DISPUTED" and not has_active_dispute(stmt["id"]):
        stmt["status"] = "ISSUED"
        touch(stmt)
    return success_object(public(d))


@bp.post("/disputes/<rid>/escalate")
def escalate_dispute(rid):
    caller = scoped_mutation_auth(["Artist"], "disputes", rid)
    d = require_path_resource("disputes", rid)
    if d["status"] not in ("OPEN", "UNDER_REVIEW"):
        raise_error(ERR_INVALID_STATE, f"cannot escalate from {d['status']}")
    d["status"] = "ESCALATED"
    touch(d)
    audit = new_record("audits", {
        "artist_id": d["artist_id"],
        "scope_statement_id": d["statement_id"],
        "source_dispute_id": d["id"],
        "status": "REQUESTED",
        "findings_underpayment_cents": None,
        "audit_cost_cents": None,
        "cost_bearer": None,
        "underpayment_applied": False,
        "cost_applied": False,
        "reopen_count": 0,
    })
    return success_object(public(audit), status=201)
