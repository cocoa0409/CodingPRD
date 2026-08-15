"""Notional fund endpoints."""
from flask import Blueprint, request

import db
from errors import ERR_PLAN_NOT_ACTIVE, raise_err
from middleware import user_context, require_role
from response import ok_object
from routes.plans import _list_response
from services.core import body, req_string, req_enum, req_int, get_or_404, stamp_new

bp = Blueprint("notional_funds", __name__)


def fund_view(f):
    return {
        "id": f["id"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
        "plan_id": f["plan_id"],
        "ticker": f["ticker"],
        "crediting_mode": f["crediting_mode"],
        "annual_rate_bp": f["annual_rate_bp"],
    }


@bp.post("/api/notional-funds")
def create_fund():
    data = body()
    from errors import ERR_INVALID_REQUEST

    plan_id = data.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        raise_err(ERR_INVALID_REQUEST, "plan_id is required and must be a string")
    ticker = req_string(data, "ticker")
    mode = req_enum(data, "crediting_mode", {"FIXED_RATE", "INDEX_LINKED"})
    rate = req_int(data, "annual_rate_bp", -10000, 10000)

    user_id, role = user_context()
    require_role(role, {"PlanSponsor"})
    plan = get_or_404(db.plans, plan_id, "Plan")
    if plan["status"] != "ACTIVE":
        raise_err(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE to create a notional fund")

    fund = stamp_new(
        {
            "plan_id": plan_id,
            "ticker": ticker,
            "crediting_mode": mode,
            "annual_rate_bp": rate,
        }
    )
    db.notional_funds[fund["id"]] = fund
    return ok_object(fund_view(fund), 201)


@bp.get("/api/notional-funds")
def list_funds():
    user_context()
    items = list(db.notional_funds.values())
    plan_id = request.args.get("plan_id")
    if plan_id is not None:
        items = [f for f in items if f["plan_id"] == plan_id]
    return _list_response([fund_view(f) for f in items], request.args)


@bp.get("/api/notional-funds/<fundId>")
def get_fund(fundId):
    user_context()
    f = get_or_404(db.notional_funds, fundId, "NotionalFund")
    return ok_object(fund_view(f))
