"""Tank endpoints (PRD §3.3, §3.7)."""
from flask import Blueprint, request

import db
import errors
from clock import clock_now
from common import (parse_pagination, paginate, sort_by_created,
                    require_int, optional_int, optional_bool, optional_enum)
from middleware import require_auth, require_role, check_owner, get_json_body
from response import object_response, array_response
from services import lookups as L
from services import calculations as C

bp = Blueprint("tanks", __name__)

DELIVERY_MODES = {"WILL_CALL", "AUTOMATIC"}
ALL_ROLES = {"AccountManager", "Dispatcher", "Driver", "Inspector", "Customer"}


def recompute_reorder(tank):
    """Recompute and store tank.reorder_status at the current clock."""
    acc = db.accounts.get(tank["account_id"])
    if acc is None:
        return
    tank["reorder_status"] = C.reorder_status_for(tank, acc, clock_now())


@bp.post("/accounts/<account_id>/tanks")
def create_tank(account_id):
    _, role = require_auth()
    require_role(role, {"AccountManager"})
    acc = L.get_account(account_id)
    body = get_json_body()

    capacity = require_int(body, "capacity_gallons", minimum=1)
    k_factor = require_int(body, "k_factor", minimum=1)
    reorder_threshold = optional_int(body, "reorder_threshold_pct",
                                     default=30, minimum=1, maximum=99)
    delivery_mode = optional_enum(body, "delivery_mode", DELIVERY_MODES, default="WILL_CALL")
    monitor_installed = optional_bool(body, "monitor_installed", default=False)
    current_gallons = optional_int(body, "current_gallons", default=0, minimum=0)

    rec = {
        "account_id": acc["id"],
        "capacity_gallons": capacity,
        "current_gallons": current_gallons,
        "reorder_threshold_pct": reorder_threshold,
        "k_factor": k_factor,
        "delivery_mode": delivery_mode,
        "monitor_installed": monitor_installed,
        "last_delivery_at": None,
        "last_reading_at": None,
        "service_status": "IN_SERVICE",
        "reorder_status": "OK",
    }
    db.stamp_create_full(rec)
    db.tanks[rec["id"]] = rec
    return object_response(L.serialize_tank(rec), 201)


@bp.get("/tanks/<tank_id>")
def get_tank(tank_id):
    user_id, role = require_auth()
    require_role(role, ALL_ROLES)
    tank = L.get_tank(tank_id)
    check_owner(role, user_id, tank["account_id"])
    return object_response(L.serialize_tank(tank), 200)


@bp.get("/tanks")
def list_tanks():
    user_id, role = require_auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")
    service_status = request.args.get("service_status")
    reorder_status = request.args.get("reorder_status")

    items = list(db.tanks.values())
    if role == "Customer":
        items = [t for t in items if t.get("account_id") == user_id]
    if account_id is not None:
        items = [t for t in items if t.get("account_id") == account_id]
    if service_status is not None:
        items = [t for t in items if t.get("service_status") == service_status]
    if reorder_status is not None:
        items = [t for t in items if t.get("reorder_status") == reorder_status]

    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([L.serialize_tank(t) for t in page], limit, offset, total)


@bp.post("/tanks/<tank_id>/lockout")
def lockout_tank(tank_id):
    _, role = require_auth()
    require_role(role, {"Inspector", "AccountManager"})
    tank = L.get_tank(tank_id)
    if tank["service_status"] != "IN_SERVICE":
        raise errors.ApiError(errors.ERR_INVALID_STATE, 409, "Tank is not IN_SERVICE")
    tank["service_status"] = "LOCKED_OUT"
    db.touch(tank)
    return object_response(L.serialize_tank(tank), 200)


@bp.post("/tanks/<tank_id>/decommission")
def decommission_tank(tank_id):
    _, role = require_auth()
    require_role(role, {"AccountManager"})
    tank = L.get_tank(tank_id)
    if tank["service_status"] != "IN_SERVICE":
        raise errors.ApiError(errors.ERR_INVALID_STATE, 409, "Tank is not IN_SERVICE")
    # No ACTIVE lease on this tank
    for lease in L.leases_for_tank(tank_id):
        if lease["status"] == "ACTIVE":
            raise errors.ApiError(errors.ERR_ACCOUNT_HAS_ACTIVE_LEASE, 409,
                                  "Tank has an active lease")
    # No SCHEDULED/HOLD orders for this tank
    for o in L.orders_for_tank(tank_id):
        if o["status"] in ("SCHEDULED", "HOLD"):
            raise errors.ApiError(errors.ERR_TANK_HAS_OPEN_ORDERS, 409,
                                  "Tank has open delivery orders")
    tank["service_status"] = "DECOMMISSIONED"
    db.touch(tank)
    return object_response(L.serialize_tank(tank), 200)


@bp.post("/tanks/<tank_id>/evaluate-reorder")
def evaluate_reorder(tank_id):
    _, role = require_auth()
    require_role(role, {"Dispatcher", "AccountManager"})
    tank = L.get_tank(tank_id)
    recompute_reorder(tank)
    db.touch(tank)
    return object_response(L.serialize_tank(tank), 200)


@bp.post("/tanks/<tank_id>/generate-auto-order")
def generate_auto_order(tank_id):
    _, role = require_auth()
    require_role(role, {"Dispatcher"})
    tank = L.get_tank(tank_id)

    if tank["delivery_mode"] != "AUTOMATIC":
        raise errors.ApiError(errors.ERR_TANK_NOT_AUTOMATIC, 409,
                              "Tank is not AUTOMATIC")
    if tank["reorder_status"] != "DUE":
        raise errors.ApiError(errors.ERR_TANK_NOT_DUE, 409, "Tank is not DUE")

    acc = db.accounts[tank["account_id"]]
    proj = C.projected_gallons(tank, acc, clock_now())
    requested = tank["capacity_gallons"] - proj

    rec = {
        "account_id": acc["id"],
        "tank_id": tank["id"],
        "route_id": None,
        "origin": "AUTOMATIC",
        "requested_gallons": requested,
        "priority": "STANDARD",
        "status": "CREATED",
        "delivered_gallons": None,
        "price_cents_per_gallon": None,
        "invoice_total_cents": None,
        "budget_plan_id": None,
    }
    db.stamp_create_full(rec)
    db.delivery_orders[rec["id"]] = rec
    return object_response(L.serialize_order(rec), 201)
