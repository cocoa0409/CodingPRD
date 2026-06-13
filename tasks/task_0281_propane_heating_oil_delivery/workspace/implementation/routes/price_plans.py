"""PricePlan endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
import errors
from clock import clock_now_iso
from common import (parse_pagination, paginate, sort_by_created,
                    require_enum, optional_int)
from middleware import require_auth, require_role, check_owner, get_json_body
from response import object_response, array_response
from services import lookups as L

bp = Blueprint("price_plans", __name__)

PLAN_TYPES = {"FIXED", "CAP", "MARKET"}


@bp.post("/accounts/<account_id>/price-plans")
def create_price_plan(account_id):
    _, role = require_auth()
    require_role(role, {"AccountManager"})
    acc = L.get_account(account_id)
    body = get_json_body()
    plan_type = require_enum(body, "plan_type", PLAN_TYPES)
    locked = optional_int(body, "locked_price_cents_per_gallon", default=None, minimum=1)
    cap = optional_int(body, "cap_price_cents_per_gallon", default=None, minimum=1)

    rec = {
        "account_id": acc["id"],
        "plan_type": plan_type,
        "locked_price_cents_per_gallon": locked,
        "cap_price_cents_per_gallon": cap,
        "status": "DRAFT",
        "effective_from": None,
    }
    db.stamp_create_full(rec)
    db.price_plans[rec["id"]] = rec
    return object_response(L.serialize_price_plan(rec), 201)


@bp.get("/price-plans/<plan_id>")
def get_price_plan(plan_id):
    user_id, role = require_auth()
    require_role(role, {"AccountManager", "Dispatcher", "Customer"})
    pp = L.get_price_plan(plan_id)
    check_owner(role, user_id, pp["account_id"])
    return object_response(L.serialize_price_plan(pp), 200)


@bp.get("/price-plans")
def list_price_plans():
    user_id, role = require_auth()
    require_role(role, {"AccountManager", "Dispatcher", "Customer"})
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")
    status = request.args.get("status")

    items = list(db.price_plans.values())
    if role == "Customer":
        # Customer reads are scoped to their own account.
        items = [p for p in items if p.get("account_id") == user_id]
    if account_id is not None:
        items = [p for p in items if p.get("account_id") == account_id]
    if status is not None:
        items = [p for p in items if p.get("status") == status]

    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([L.serialize_price_plan(p) for p in page], limit, offset, total)


@bp.post("/accounts/<account_id>/price-plans/<plan_id>/activate")
def activate_price_plan(account_id, plan_id):
    _, role = require_auth()
    require_role(role, {"AccountManager"})
    acc = L.get_account(account_id)
    pp = L.get_price_plan(plan_id)
    if pp["account_id"] != acc["id"]:
        raise errors.ApiError(errors.ERR_NOT_FOUND, 404, "Price plan not under account")

    if pp["status"] != "DRAFT":
        raise errors.ApiError(errors.ERR_INVALID_STATE, 409, "Plan is not DRAFT")

    plan_type = pp["plan_type"]
    if plan_type == "FIXED" and pp.get("locked_price_cents_per_gallon") is None:
        raise errors.ApiError(errors.ERR_PLAN_PRICE_REQUIRED, 409,
                              "FIXED plan requires locked price")
    if plan_type == "CAP" and pp.get("cap_price_cents_per_gallon") is None:
        raise errors.ApiError(errors.ERR_PLAN_PRICE_REQUIRED, 409,
                              "CAP plan requires cap price")
    if plan_type == "MARKET":
        if L.active_market_price(acc["region_code"], acc["fuel_type"]) is None:
            raise errors.ApiError(errors.ERR_NO_MARKET_PRICE, 409,
                                  "No ACTIVE market price for region/fuel")

    # Cascade: expire any prior ACTIVE plan on this account.
    for other in db.price_plans.values():
        if (other["id"] != pp["id"] and other["account_id"] == acc["id"]
                and other["status"] == "ACTIVE"):
            other["status"] = "EXPIRED"
            db.touch(other)

    pp["status"] = "ACTIVE"
    pp["effective_from"] = clock_now_iso()
    db.touch(pp)

    acc["active_price_plan_id"] = pp["id"]
    db.touch(acc)

    return object_response(L.serialize_price_plan(pp), 200)
