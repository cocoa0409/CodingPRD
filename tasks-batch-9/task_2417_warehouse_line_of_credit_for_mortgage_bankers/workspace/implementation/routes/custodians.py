"""Document-custodian routes (PRD 3.1)."""

from flask import Blueprint

from db import by_created_at, db, touch
from errors import ApiError
from middleware import (
    COLLATERAL_ANALYST,
    CREDIT_OFFICER,
    CUSTODIAN,
    own_custodian,
    require_auth,
)
from response import ok
from routes.common import filter_by, get_custodian, list_response
from serializers import custodian_out, receipt_out
from validation import body, v_string

bp = Blueprint("custodians", __name__)


@bp.get("/custodians/<custodian_id>")
def read_custodian(custodian_id):
    require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST, CUSTODIAN])
    custodian = get_custodian(custodian_id)
    return ok(custodian_out(custodian))


@bp.post("/custodians/<custodian_id>/suspend")
def suspend_custodian(custodian_id):
    require_auth([CREDIT_OFFICER])
    custodian = get_custodian(custodian_id)
    data = body()
    v_string(data, "reason", max_len=500)
    # priority 45: SUSPENDED is terminal on this axis
    if custodian["status"] != "APPROVED":
        raise ApiError("ERR_CUSTODIAN_INVALID_STATE",
                       "Only an APPROVED custodian may be suspended.")
    custodian["status"] = "SUSPENDED"
    touch(custodian)
    return ok(custodian_out(custodian))


@bp.get("/custodians/<custodian_id>/receipts")
def list_custodian_receipts(custodian_id):
    user_id, role = require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST, CUSTODIAN])
    custodian = get_custodian(custodian_id)
    own_custodian(user_id, role, custodian["id"])
    rows = by_created_at([r for r in db.receipts.values()
                          if r["custodian_id"] == custodian["id"]])
    rows = filter_by(rows, "status")
    rows = filter_by(rows, "advance_id")
    return list_response(rows, receipt_out)
