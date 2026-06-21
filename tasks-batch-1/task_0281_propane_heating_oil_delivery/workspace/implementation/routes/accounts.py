"""Account endpoints (PRD §3.1)."""
from flask import Blueprint

import db
import errors
from common import (parse_pagination, paginate, sort_by_created,
                    require_string, require_enum)
from middleware import require_auth, require_role, check_owner, get_json_body
from response import object_response, array_response
from services import lookups as L

bp = Blueprint("accounts", __name__)

FUEL_TYPES = {"PROPANE", "HEATING_OIL"}
ALL_ROLES = {"AccountManager", "Dispatcher", "Driver", "Inspector", "Customer"}


@bp.post("/accounts")
def create_account():
    _, role = require_auth()
    require_role(role, {"AccountManager"})
    body = get_json_body()
    customer_name = require_string(body, "customer_name")
    region_code = require_string(body, "region_code")
    fuel_type = require_enum(body, "fuel_type", FUEL_TYPES)

    rec = {
        "customer_name": customer_name,
        "region_code": region_code,
        "fuel_type": fuel_type,
        "service_status": "ACTIVE",
        "credit_balance_cents": 0,
        "active_price_plan_id": None,
    }
    db.stamp_create_full(rec)
    db.accounts[rec["id"]] = rec
    return object_response(L.serialize_account(rec), 201)


@bp.get("/accounts/<account_id>")
def get_account(account_id):
    user_id, role = require_auth()
    require_role(role, ALL_ROLES)
    acc = L.get_account(account_id)
    check_owner(role, user_id, acc["id"])
    return object_response(L.serialize_account(acc), 200)


@bp.get("/accounts")
def list_accounts():
    _, role = require_auth()
    require_role(role, {"AccountManager", "Dispatcher"})
    limit, offset = parse_pagination()

    from flask import request
    region_code = request.args.get("region_code")
    service_status = request.args.get("service_status")
    active_price_plan_id = request.args.get("active_price_plan_id")

    items = list(db.accounts.values())
    if region_code is not None:
        items = [a for a in items if a.get("region_code") == region_code]
    if service_status is not None:
        items = [a for a in items if a.get("service_status") == service_status]
    if active_price_plan_id is not None:
        items = [a for a in items if a.get("active_price_plan_id") == active_price_plan_id]

    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([L.serialize_account(a) for a in page], limit, offset, total)


@bp.post("/accounts/<account_id>/suspend")
def suspend_account(account_id):
    _, role = require_auth()
    require_role(role, {"AccountManager"})
    acc = L.get_account(account_id)
    if acc["service_status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_INVALID_STATE, 409, "Account is not ACTIVE")
    acc["service_status"] = "SUSPENDED"
    db.touch(acc)
    return object_response(L.serialize_account(acc), 200)


@bp.post("/accounts/<account_id>/reactivate")
def reactivate_account(account_id):
    _, role = require_auth()
    require_role(role, {"AccountManager"})
    acc = L.get_account(account_id)
    if acc["service_status"] != "SUSPENDED":
        raise errors.ApiError(errors.ERR_INVALID_STATE, 409, "Account is not SUSPENDED")
    acc["service_status"] = "ACTIVE"
    db.touch(acc)
    return object_response(L.serialize_account(acc), 200)


@bp.post("/accounts/<account_id>/close")
def close_account(account_id):
    _, role = require_auth()
    require_role(role, {"AccountManager"})
    acc = L.get_account(account_id)
    if acc["service_status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_INVALID_STATE, 409, "Account is not ACTIVE")

    # No open orders (CREATED/SCHEDULED/HOLD)
    for o in L.orders_for_account(account_id):
        if o["status"] in ("CREATED", "SCHEDULED", "HOLD"):
            raise errors.ApiError(
                errors.ERR_ACCOUNT_HAS_OPEN_ORDERS, 409,
                "Account has open delivery orders")
    # No ACTIVE lease under any of the account's tanks
    for t in L.tanks_for_account(account_id):
        for lease in L.leases_for_tank(t["id"]):
            if lease["status"] == "ACTIVE":
                raise errors.ApiError(
                    errors.ERR_ACCOUNT_HAS_ACTIVE_LEASE, 409,
                    "Account has an active tank lease")

    acc["service_status"] = "CLOSED"
    db.touch(acc)
    return object_response(L.serialize_account(acc), 200)
