"""Chargeback endpoints: list, get, recoveries, write-off."""
from flask import Blueprint

from db import DB
from errors import ApiError
from middleware import auth, ADMIN, ADMIN_ACCT, ALL_ROLES
from response import ok
from services import ser_chargeback, touch
from util import apply_filters, as_pos_int, get_body, is_int, req, respond_list

bp = Blueprint("chargebacks", __name__)


@bp.get("/agency/chargebacks")
def list_chargebacks():
    auth(ALL_ROLES)
    items = apply_filters(
        DB["chargebacks"].values(),
        {
            "policy_id": "policy_id",
            "producer_id": "producer_id",
            "commission_entry_id": "commission_entry_id",
            "status": "status",
        },
    )
    return respond_list(items, ser_chargeback)


@bp.get("/agency/chargebacks/<chargebackId>")
def get_chargeback(chargebackId):
    auth(ALL_ROLES)
    c = DB["chargebacks"].get(chargebackId)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Chargeback not found")
    return ok(ser_chargeback(c))


@bp.post("/agency/chargebacks/<chargebackId>/recoveries")
def record_recovery(chargebackId):
    auth(ADMIN_ACCT)
    c = DB["chargebacks"].get(chargebackId)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Chargeback not found")
    # Priority 4: state admissibility (RECOVERED / WRITTEN_OFF are terminal).
    if c["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Chargeback is not PENDING")
    data = get_body()
    # Priority 9: recovery must not exceed the outstanding amount.
    amount = data.get("amount_cents")
    outstanding = c["amount_cents"] - c["recovered_cents"]
    if is_int(amount) and amount > 0 and amount > outstanding:
        raise ApiError(
            "ERR_RECOVERY_EXCEEDS_OUTSTANDING",
            409,
            "Recovery exceeds the chargeback outstanding_cents",
        )
    # Priority 10: shape.
    amount = as_pos_int(req(data, "amount_cents"), "amount_cents")
    c["recovered_cents"] += amount
    if c["recovered_cents"] == c["amount_cents"]:
        c["status"] = "RECOVERED"
    touch(c)
    return ok(ser_chargeback(c))


@bp.post("/agency/chargebacks/<chargebackId>/write-off")
def write_off(chargebackId):
    auth(ADMIN)
    c = DB["chargebacks"].get(chargebackId)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Chargeback not found")
    # Priority 4: state admissibility.
    if c["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Chargeback is not PENDING")
    # Priority 7: the chargeback's producer must be TERMINATED.
    producer = DB["producers"].get(c["producer_id"])
    if producer is None or producer["status"] != "TERMINATED":
        raise ApiError(
            "ERR_PRODUCER_NOT_TERMINATED", 409, "Chargeback producer is not TERMINATED"
        )
    c["status"] = "WRITTEN_OFF"
    touch(c)
    return ok(ser_chargeback(c))
