"""Transportation fund endpoints."""
from flask import Blueprint, request

import db
from errors import bad_request, not_found, ERR_FUND_NOT_FOUND
from middleware import get_caller, require_roles, ALL_ROLES
from response import success, success_list, parse_pagination
from services.core import new_record, serialize, recompute_fund

bp = Blueprint("funds", __name__)


@bp.post("/parking/transportation-funds")
def create_fund():
    caller = get_caller()
    require_roles(caller, ["ParkingAdmin"])
    body = request.get_json(silent=True) or {}

    fund_code = body.get("fund_code")
    if not isinstance(fund_code, str) or not fund_code:
        raise bad_request("fund_code is required")

    record = new_record()
    record.update(
        fund_code=fund_code,
        permit_revenue_cents=0,
        citation_revenue_cents=0,
        committed_shuttle_funding_cents=0,
        available_balance_cents=0,
    )
    db.funds[record["id"]] = record
    return success(serialize(record), 201)


@bp.get("/parking/transportation-funds")
def list_funds():
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.funds.values())
    for f in items:
        recompute_fund(f)
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([serialize(f) for f in page], limit, offset, total)


@bp.get("/parking/transportation-funds/<fundId>")
def get_fund(fundId):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    record = db.funds.get(fundId)
    if record is None:
        raise not_found(ERR_FUND_NOT_FOUND, "No transportation fund with the given id")
    recompute_fund(record)
    return success(serialize(record), 200)
