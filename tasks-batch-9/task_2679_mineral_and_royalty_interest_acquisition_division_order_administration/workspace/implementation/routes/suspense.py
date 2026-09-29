"""Suspense resolution: release and escheat (PRD 3.9)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import response
import serializers
from db import db, touch
from errors import ApiError
from guards import (authorize, body, get_suspense, pagination, paginate,
                    req_str)
from services import cascade

bp = Blueprint("suspense", __name__)


@bp.route("/suspense-accounts/<account_id>", methods=["GET"])
def read_account(account_id):
    authorize("DivisionOrderAdmin", "RoyaltyOwner")
    row = get_suspense(account_id)
    return response.ok(serializers.suspense_out(row))


@bp.route("/suspense-accounts", methods=["GET"])
def list_accounts():
    authorize("DivisionOrderAdmin", "RoyaltyOwner")
    limit, offset = pagination()
    rows = list(db.suspense_accounts.values())
    for field in ("division_order_id", "royalty_owner_id", "suspense_status",
                  "suspense_reason"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows.sort(key=lambda r: r["_seq"])
    page, total = paginate(rows, limit, offset)
    return response.listing([serializers.suspense_out(r) for r in page],
                            limit, offset, total)


@bp.route("/suspense-accounts/<account_id>/release", methods=["POST"])
def release_account(account_id):
    user_id, _role = authorize("DivisionOrderAdmin")
    account = get_suspense(account_id)

    if account["suspense_status"] != "ACCRUING":            # priority 33
        raise ApiError("ERR_SUSPENSE_STATE_INVALID")
    order = db.division_orders.get(account["division_order_id"])
    if order is not None and order["created_by_user_id"] == user_id:   # priority 51
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    owner = db.royalty_owners.get(account["royalty_owner_id"])
    if owner is None or owner["contact_status"] != "LOCATED":          # priority 52
        raise ApiError("ERR_OWNER_UNLOCATABLE")
    if not owner["tax_id_on_file"]:                                    # priority 53
        raise ApiError("ERR_OWNER_TAX_ID_MISSING")

    cascade.release_cascade(account, order, user_id)
    return response.ok(serializers.suspense_out(account))


@bp.route("/suspense-accounts/<account_id>/escheat", methods=["POST"])
def escheat_account(account_id):
    authorize("DivisionOrderAdmin")
    account = get_suspense(account_id)
    payload = body()
    escheat_state_code = req_str(payload, "escheat_state_code")

    if account["suspense_status"] != "ACCRUING":            # priority 33
        raise ApiError("ERR_SUSPENSE_STATE_INVALID")
    if account["suspense_reason"] != "UNLOCATABLE_OWNER":   # priority 54
        raise ApiError("ERR_ESCHEAT_REASON_INVALID")
    serializers.refresh_suspense(account)
    if account["months_held"] < calc.ESCHEAT_MONTHS:        # priority 64
        raise ApiError("ERR_ESCHEAT_PERIOD_NOT_ELAPSED")

    account["suspense_status"] = "ESCHEATED"
    account["escheat_state_code"] = escheat_state_code
    account["accrued_amount"] = Decimal("0.00")
    account["held_detail_count"] = 0
    touch(account)
    # the parent division order deliberately stays SUSPENDED
    return response.ok(serializers.suspense_out(account))
