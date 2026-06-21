"""Test-driving clock endpoints (PRD §3.9)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import require_auth, get_json_body
from response import ok_object
from services.validation import require_fields


bp = Blueprint("clock", __name__)


@bp.post("/freight/_clock/set_current_utc")
def set_clock():
    require_auth(["BrokerOps"])()
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    iso = body["to_iso8601"]
    try:
        db.parse_iso_dt(iso)
    except (ValueError, TypeError, AttributeError):
        raise APIError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be ISO 8601")
    state = db.set_current_utc(iso)
    return ok_object(state, 200)


@bp.post("/freight/_clock/advance")
def advance_clock():
    require_auth(["BrokerOps"])()
    now_dt = db.parse_iso_dt(db.get_current_utc())
    expired_quote_ids = []
    expired_contract_ids = []

    # QuoteRequest: OPEN -> EXPIRED when expires_at_utc <= current_utc.
    for qr in list(db.quote_requests.values()):
        if qr.get("status") != "OPEN":
            continue
        exp = db.parse_iso_dt(qr.get("expires_at_utc"))
        if exp is None:
            continue
        if now_dt >= exp:
            qr["status"] = "EXPIRED"
            db.bump(qr)
            expired_quote_ids.append(qr["id"])

    # ContractRate: ACTIVE -> EXPIRED when effective_until_utc <= current_utc.
    for cr in list(db.contract_rates.values()):
        if cr.get("status") != "ACTIVE":
            continue
        until = db.parse_iso_dt(cr.get("effective_until_utc"))
        if until is None:
            continue
        if now_dt >= until:
            cr["status"] = "EXPIRED"
            db.bump(cr)
            expired_contract_ids.append(cr["id"])

    return ok_object(
        {
            "expired_quote_request_ids": expired_quote_ids,
            "expired_contract_rate_ids": expired_contract_ids,
        },
        200,
    )
