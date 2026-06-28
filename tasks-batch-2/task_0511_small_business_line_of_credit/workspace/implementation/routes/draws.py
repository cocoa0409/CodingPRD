"""Draw routes (PRD §3.4). Draw against an ACTIVE line; compute fee, append
DRAW_PRINCIPAL + DRAW_FEE ledger entries, recompute outstanding.

Guard order: not-drawable (parent line not ACTIVE) precedes limit-exceeded.
"""
from flask import Blueprint, request

import db
import serialize
from common import (parse_body, require_int, stamp_create, touch, list_response, now)
from errors import err, ERR_INVALID_STATE, ERR_LINE_NOT_DRAWABLE, ERR_LIMIT_EXCEEDED
from lookups import get_credit_line, get_draw
from middleware import auth_and_role
from response import object_response
from services import calc, ledger

bp = Blueprint("draws", __name__)


@bp.post("/credit-lines/<rid>/draws")
def create_draw(rid):
    auth_and_role(["Servicer"])
    cl = get_credit_line(rid)
    body = parse_body()
    # priority 5: well-formedness (principal_cents > 0).
    principal = require_int(body, "principal_cents", exclusive_min=0)

    # priority 16: line must be ACTIVE (precedes the fiscal limit check).
    if cl["status"] != "ACTIVE":
        raise err(ERR_LINE_NOT_DRAWABLE, "Line is not ACTIVE; draws are blocked")
    # priority 17: must not exceed available credit (equality allowed).
    if principal > cl["available_credit_cents"]:
        raise err(ERR_LIMIT_EXCEEDED, "Draw would exceed credit limit")

    fee = calc.draw_fee(principal_cents=principal, fee_factor_bps=cl["fee_factor_bps"])
    record = {
        "credit_line_id": cl["id"],
        "principal_cents": principal,
        "fee_cents": fee,
        "principal_repaid_cents": 0,
        "fee_repaid_cents": 0,
        "drawn_at": None,
        "status": "OUTSTANDING",
    }
    stamp_create(record)
    # drawn_at stamped from the logical clock; keep a precise dt for FIFO ordering.
    from common import iso_millis
    record["drawn_at"] = iso_millis(now())
    record["_drawn_at_dt"] = now()
    db.draws[record["id"]] = record

    # ledger: DRAW_PRINCIPAL then DRAW_FEE. balance_after tracks outstanding principal.
    balance = ledger.current_principal_balance(cl["id"])
    balance = balance + principal
    ledger.append_entry(
        credit_line_id=cl["id"], draw_id=record["id"], remittance_id=None,
        entry_type="DRAW_PRINCIPAL", amount_cents=principal, balance_after_cents=balance,
    )
    ledger.append_entry(
        credit_line_id=cl["id"], draw_id=record["id"], remittance_id=None,
        entry_type="DRAW_FEE", amount_cents=fee, balance_after_cents=balance,
    )

    ledger.recompute_outstanding(cl)
    touch(cl)
    return object_response(serialize.draw(record), 201)


@bp.get("/draws/<rid>")
def fetch_draw(rid):
    auth_and_role(["Underwriter", "Servicer", "CreditOfficer"])
    d = get_draw(rid)
    return object_response(serialize.draw(d), 200)


@bp.get("/credit-lines/<rid>/draws")
def list_draws(rid):
    auth_and_role(["Underwriter", "Servicer", "CreditOfficer"])
    get_credit_line(rid)
    status = request.args.get("status")
    draws = [d for d in db.draws.values() if d["credit_line_id"] == rid]
    if status is not None:
        draws = [d for d in draws if d["status"] == status]
    return list_response(draws, serialize.draw)
