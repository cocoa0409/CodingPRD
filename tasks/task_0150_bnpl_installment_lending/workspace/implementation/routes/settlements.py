"""MerchantSettlement endpoints (PRD §3.8)."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, require_role, require_merchant_owns
from response import success
from services import engine
from services.engine import touch, serialize_settlement, _parse_iso
from routes.common import (
    parse_pagination, paginate, sort_by_created, require_settlement,
)

bp = Blueprint("settlements", __name__)


@bp.route("/merchant-settlements/<settlement_id>", methods=["GET"])
def get_settlement(settlement_id):
    uid, role = authenticate()
    require_role(role, {"Servicer", "Merchant"})
    s = require_settlement(settlement_id)
    require_merchant_owns(role, uid, s["merchant_id"])
    return success(serialize_settlement(s), status=200)


@bp.route("/merchant-settlements", methods=["GET"])
def list_settlements():
    uid, role = authenticate()
    require_role(role, {"Servicer", "Merchant"})
    limit, offset = parse_pagination()
    merchant_filter = request.args.get("merchant_id")
    loan_filter = request.args.get("loan_id")

    rows = list(db.merchant_settlements.values())
    if merchant_filter is not None:
        rows = [s for s in rows if s["merchant_id"] == merchant_filter]
    if loan_filter is not None:
        rows = [s for s in rows if s["loan_id"] == loan_filter]
    if role == "Merchant":
        rows = [s for s in rows if s["merchant_id"] == uid]

    rows = sort_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return success([serialize_settlement(s) for s in page],
                   status=200, pagination=meta)


@bp.route("/merchant-settlements/<settlement_id>/release", methods=["POST"])
def release_settlement(settlement_id):
    _uid, role = authenticate()
    require_role(role, {"Servicer"})
    s = require_settlement(settlement_id)

    loan = db.loans.get(s["loan_id"])

    # State: only a PENDING settlement may be released.
    if s["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Only a PENDING settlement may be released.")

    # Temporal (priority 8): now >= loan.created_at + merchant.settlement_hold_days.
    merchant = db.merchants[s["merchant_id"]]
    loan_created = _parse_iso(loan["created_at"])
    release_eligible_at = loan_created + timedelta(days=merchant["settlement_hold_days"])
    if db.now() < release_eligible_at:
        raise err("ERR_SETTLEMENT_HOLD_ACTIVE",
                  "Settlement hold window has not yet elapsed.")

    # Loan must still be ACTIVE.
    if loan["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE",
                  "Loan is no longer ACTIVE; settlement cannot be released.")

    s["status"] = "RELEASED"
    touch(s)
    engine.reconcile_merchant(s["merchant_id"])
    return success(serialize_settlement(s), status=200)
