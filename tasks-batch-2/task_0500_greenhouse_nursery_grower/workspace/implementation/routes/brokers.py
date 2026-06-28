import re
from flask import Blueprint, request

from core import (store, require, get_body, get_or_404, ok, ok_list, paginate, common_create, touch,
                  req_str, req_int, ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_FORBIDDEN)

bp = Blueprint("brokers", __name__)


@bp.post("/nursery/brokers")
def create_broker():
    require(["SalesCoordinator"])
    body = get_body()
    company_name = req_str(body, "company_name")
    contact_email = req_str(body, "contact_email")
    ship_to_state = req_str(body, "ship_to_state")
    if not re.fullmatch(r"[A-Z]{2}", ship_to_state):
        raise ApiError(ERR_INVALID_REQUEST, "ship_to_state must be two uppercase letters")
    credit_limit_cents = req_int(body, "credit_limit_cents", minimum=0)
    br = common_create({
        "company_name": company_name,
        "contact_email": contact_email,
        "ship_to_state": ship_to_state,
        "credit_limit_cents": credit_limit_cents,
        "open_balance_cents": 0,
        "status": "ACTIVE",
    })
    store.brokers[br["id"]] = br
    return ok(br, 201)


@bp.get("/nursery/brokers/<brid>")
def get_broker(brid):
    uid, role = require(["SalesCoordinator", "Broker"])
    br = get_or_404(store.brokers, brid)
    if role == "Broker" and br["id"] != uid:
        raise ApiError(ERR_FORBIDDEN, "Broker may only read its own account")
    return ok(br)


@bp.get("/nursery/brokers")
def list_brokers():
    require(["SalesCoordinator"])
    rows = list(store.brokers.values())
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


@bp.post("/nursery/brokers/<brid>/hold")
def hold_broker(brid):
    require(["SalesCoordinator"])
    br = get_or_404(store.brokers, brid)
    if br["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Broker is not ACTIVE")
    br["status"] = "ON_HOLD"
    touch(br)
    return ok(br)


@bp.post("/nursery/brokers/<brid>/reinstate")
def reinstate_broker(brid):
    require(["SalesCoordinator"])
    br = get_or_404(store.brokers, brid)
    if br["status"] != "ON_HOLD":
        raise ApiError(ERR_INVALID_STATE, "Broker is not ON_HOLD")
    br["status"] = "ACTIVE"
    touch(br)
    return ok(br)
