"""FleetAccount endpoints (PRD §3.1, §3.11) including suspend/reactivate cascade."""
from flask import Blueprint, request

import db
from auth import require_role
from common import (get_json_or_400, require_str, require_number, require_int,
                    parse_pagination, paginate, sort_by_created, stamp_create, new_id,
                    touch)
from errors import ApiError, ERR_INVALID_STATE, ERR_FLEET_HAS_OPEN_BALANCE, ERR_FORBIDDEN
from response import success_object, success_array
from services import lookup, pricing
from services import fleet as fleet_svc
from services.serialize import fleet_account_out, vehicle_out

bp = Blueprint("fleet_accounts", __name__)

READ_ROLES = ("ShopManager", "FleetManager")


def _fleet_scope_or_403(role, uid, fleet_account_id):
    """A FleetManager may only read/act within its own account (PRD §2.1)."""
    if role == "FleetManager" and uid != fleet_account_id:
        raise ApiError(ERR_FORBIDDEN, 403, "fleet manager may only act on its own account")


@bp.route("/fleet-accounts", methods=["POST"])
def create_fleet_account():
    require_role("ShopManager")
    body = get_json_or_400()
    shop_id = require_str(body, "shop_id")
    company_name = require_str(body, "company_name")
    discount_pct = require_number(body, "discount_pct", minimum=0, maximum=1,
                                  min_inclusive=True, max_inclusive=False)
    credit_limit = require_int(body, "credit_limit_cents", minimum=0)
    lookup.get_shop(shop_id)
    acct = {
        "id": new_id(),
        "shop_id": shop_id,
        "company_name": company_name,
        "discount_pct": discount_pct,
        "credit_limit_cents": credit_limit,
        "status": "ACTIVE",
    }
    stamp_create(acct)
    db.fleet_accounts[acct["id"]] = acct
    return success_object(fleet_account_out(acct), 201)


@bp.route("/fleet-accounts", methods=["GET"])
def list_fleet_accounts():
    role, uid = _auth_read()
    limit, offset = parse_pagination()
    rows = list(db.fleet_accounts.values())
    if role == "FleetManager":
        rows = [a for a in rows if a["id"] == uid]
    shop_id = request.args.get("shop_id")
    if shop_id is not None:
        rows = [a for a in rows if a["shop_id"] == shop_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([fleet_account_out(a) for a in page], limit, offset, total)


@bp.route("/fleet-accounts/<fleet_id>", methods=["GET"])
def get_fleet_account(fleet_id):
    role, uid = _auth_read()
    acct = lookup.get_fleet_account(fleet_id)
    _fleet_scope_or_403(role, uid, fleet_id)
    return success_object(fleet_account_out(acct), 200)


@bp.route("/fleet-accounts/<fleet_id>/vehicles", methods=["GET"])
def list_fleet_vehicles(fleet_id):
    role, uid = _auth_read()
    lookup.get_fleet_account(fleet_id)
    _fleet_scope_or_403(role, uid, fleet_id)
    limit, offset = parse_pagination()
    rows = [v for v in db.vehicles.values() if v.get("fleet_account_id") == fleet_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([vehicle_out(v) for v in page], limit, offset, total)


@bp.route("/fleet-accounts/<fleet_id>/suspend", methods=["POST"])
def suspend_fleet_account(fleet_id):
    require_role("ShopManager")
    acct = lookup.get_fleet_account(fleet_id)
    if acct["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "account is not ACTIVE")
    acct["status"] = "SUSPENDED"
    touch(acct)
    _reprice_draft_orders(fleet_id)
    return success_object(fleet_account_out(acct), 200)


@bp.route("/fleet-accounts/<fleet_id>/reactivate", methods=["POST"])
def reactivate_fleet_account(fleet_id):
    require_role("ShopManager")
    acct = lookup.get_fleet_account(fleet_id)
    if acct["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "account is not SUSPENDED")
    acct["status"] = "ACTIVE"
    touch(acct)
    _reprice_draft_orders(fleet_id)
    return success_object(fleet_account_out(acct), 200)


@bp.route("/fleet-accounts/<fleet_id>/close", methods=["POST"])
def close_fleet_account(fleet_id):
    require_role("ShopManager")
    acct = lookup.get_fleet_account(fleet_id)
    if fleet_svc.reserved_credit(fleet_id) != 0:
        raise ApiError(ERR_FLEET_HAS_OPEN_BALANCE, 409,
                       "account has outstanding reserved credit")
    acct["status"] = "CLOSED"
    touch(acct)
    return success_object(fleet_account_out(acct), 200)


def _reprice_draft_orders(fleet_id):
    """Re-price every DRAFT work order of a vehicle on this account (PRD §3.11)."""
    veh_ids = {v["id"] for v in db.vehicles.values()
               if v.get("fleet_account_id") == fleet_id}
    for w in db.work_orders.values():
        if w["vehicle_id"] in veh_ids and w["service_status"] == "DRAFT":
            pricing.recompute_pricing(w)
            touch(w)


def _auth_read():
    role, uid = require_role(*READ_ROLES)
    return role, uid
