"""Statement routes (PRD §3.8). Open (overlap-checked), finalize (reconstruct
window totals from the immutable ledger)."""
from flask import Blueprint, request

import db
import serialize
from common import (parse_body, require_fields, parse_datetime, stamp_create, touch,
                    list_response, now)
from errors import err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_VALIDATION, ERR_STATEMENT_OVERLAP
from lookups import get_credit_line, get_statement
from middleware import auth_and_role
from response import object_response

bp = Blueprint("statements", __name__)


@bp.post("/credit-lines/<rid>/statements")
def open_statement(rid):
    auth_and_role(["Servicer"])
    cl = get_credit_line(rid)
    body = parse_body()
    require_fields(body, ["period_start", "period_end"])
    start_dt = parse_datetime(body["period_start"])
    end_dt = parse_datetime(body["period_end"])
    if start_dt is None or end_dt is None:
        raise err(ERR_INVALID_REQUEST, "period_start/period_end must be valid ISO8601 instants")
    # semantic validation (ERR_VALIDATION 422): period_end strictly after period_start.
    if not (end_dt > start_dt):
        raise err(ERR_VALIDATION, "period_end must be strictly after period_start")

    # priority 15: closed-containment overlap on the same line.
    # collide iff new.start < existing.end AND existing.start < new.end (adjacency allowed).
    for other in db.statements.values():
        if other["credit_line_id"] != cl["id"]:
            continue
        o_start = other["_period_start_dt"]
        o_end = other["_period_end_dt"]
        if start_dt < o_end and o_start < end_dt:
            raise err(ERR_STATEMENT_OVERLAP, "Statement window overlaps an existing statement")

    record = {
        "credit_line_id": cl["id"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "opening_principal_cents": None,
        "draws_total_cents": None,
        "fees_assessed_cents": None,
        "remittances_total_cents": None,
        "closing_principal_cents": None,
        "status": "OPEN",
    }
    stamp_create(record)
    record["_period_start_dt"] = start_dt
    record["_period_end_dt"] = end_dt
    db.statements[record["id"]] = record
    return object_response(serialize.statement(record), 201)


@bp.get("/statements/<rid>")
def fetch_statement(rid):
    auth_and_role(["Underwriter", "Servicer", "CreditOfficer"])
    s = get_statement(rid)
    return object_response(serialize.statement(s), 200)


@bp.get("/credit-lines/<rid>/statements")
def list_statements_for_line(rid):
    auth_and_role(["Underwriter", "Servicer", "CreditOfficer"])
    get_credit_line(rid)
    status = request.args.get("status")
    items = [x for x in db.statements.values() if x["credit_line_id"] == rid]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return list_response(items, serialize.statement)


@bp.post("/statements/<rid>/finalize")
def finalize_statement(rid):
    auth_and_role(["Servicer"])
    s = get_statement(rid)
    # state legality (priority 6).
    if s["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Statement is not OPEN")
    # temporal precondition: now >= period_end.
    if now() < s["_period_end_dt"]:
        raise err(ERR_INVALID_STATE, "Statement period has not yet ended")

    line_id = s["credit_line_id"]
    start_dt = s["_period_start_dt"]
    end_dt = s["_period_end_dt"]

    # ledger entries ordered by created_at ASC, tie-break creation seq (never id).
    entries = sorted(
        [e for e in db.ledger_entries.values() if e["credit_line_id"] == line_id],
        key=lambda e: (e["_created_dt"], e["_seq"]),
    )

    # opening = balance_after of latest entry with created_at < period_start (else 0).
    opening = 0
    for e in entries:
        if e["_created_dt"] < start_dt:
            opening = e["balance_after_cents"]
        else:
            break

    # closing = balance_after of latest entry with created_at < period_end (else opening).
    closing = opening
    found_in_window = False
    for e in entries:
        if e["_created_dt"] < end_dt:
            closing = e["balance_after_cents"]
            found_in_window = True
    if not found_in_window:
        closing = opening

    # draws_total / fees_assessed: draws whose drawn_at in [start, end).
    draws_total = 0
    fees_assessed = 0
    for d in db.draws.values():
        if d["credit_line_id"] != line_id:
            continue
        dat = d["_drawn_at_dt"]
        if start_dt <= dat < end_dt:
            draws_total += d["principal_cents"]
            fees_assessed += d["fee_cents"]

    # remittances_total: SETTLED remittances whose settle time (updated_at) in [start, end).
    remittances_total = 0
    for r in db.remittances.values():
        if r["credit_line_id"] != line_id:
            continue
        if r["status"] != "SETTLED":
            continue
        rat = r["_updated_dt"]
        if start_dt <= rat < end_dt:
            remittances_total += r["amount_cents"]

    s["opening_principal_cents"] = opening
    s["draws_total_cents"] = draws_total
    s["fees_assessed_cents"] = fees_assessed
    s["remittances_total_cents"] = remittances_total
    s["closing_principal_cents"] = closing
    s["status"] = "FINALIZED"
    touch(s)
    return object_response(serialize.statement(s), 200)
