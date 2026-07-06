from __future__ import annotations
from flask import Blueprint, request

from db import db, stamp_common, bump
from errors import raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import require_roles
from pagination import parse_limit_offset, paginate
from response import created, ok, list_response
from routes._helpers import get_body, require_field, as_int, fetch, clean
from services import order as osvc

bp = Blueprint("helium", __name__)


# ---- Attach HeliumOrder to Order ------------------------------------

@bp.route("/orders/<id>/helium", methods=["POST"])
@require_roles("StoreClerk")
def attach_helium(id):
    order = fetch(db.orders, id)
    if order["fulfillment_status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "helium may only attach to DRAFT order")
    if osvc.helium_order_for(id) is not None:
        raise_error(ERR_INVALID_STATE, "Order already has HeliumOrder")

    body = get_body()
    latex_count = as_int(require_field(body, "latex_count"), "latex_count")
    foil_count = as_int(require_field(body, "foil_count"), "foil_count")
    if latex_count < 0 or foil_count < 0:
        raise_error(ERR_INVALID_REQUEST, "counts must be >= 0")

    h = {
        "order_id": id,
        "latex_count": latex_count,
        "foil_count": foil_count,
        "helium_tank_ids": [],
        "fill_fee_cents": 0,
    }
    stamp_common(h)
    db.helium_orders[h["id"]] = h
    return created(clean(h))


@bp.route("/orders/<id>/helium", methods=["GET"])
@require_roles("StoreClerk", "Customer")
def get_helium(id):
    fetch(db.orders, id)  # existence
    items = [h for h in db.helium_orders.values() if h["order_id"] == id]
    # Endpoint output is HeliumOrder[] per scaffold — return as array without pagination
    limit, offset = parse_limit_offset()
    page, total = paginate(items, limit, offset)
    return list_response([clean(x) for x in page], limit, offset, total)


# ---- HeliumTank -----------------------------------------------------

@bp.route("/helium-tanks", methods=["POST"])
@require_roles("StoreManager")
def create_tank():
    body = get_body()
    tank_code = require_field(body, "tank_code")
    capacity_cubic_ft = as_int(require_field(body, "capacity_cubic_ft"), "capacity_cubic_ft")
    if not isinstance(tank_code, str) or not tank_code:
        raise_error(ERR_INVALID_REQUEST, "tank_code must be non-empty string")
    if capacity_cubic_ft < 0:
        raise_error(ERR_INVALID_REQUEST, "capacity_cubic_ft must be >= 0")
    for existing in db.helium_tanks.values():
        if existing["tank_code"] == tank_code:
            raise_error(ERR_INVALID_REQUEST, f"tank_code '{tank_code}' already exists")
    tank = {
        "tank_code": tank_code,
        "capacity_cubic_ft": capacity_cubic_ft,
        "remaining_cubic_ft": capacity_cubic_ft,
        "status": "ACTIVE",
    }
    stamp_common(tank)
    db.helium_tanks[tank["id"]] = tank
    return created(clean(tank))


@bp.route("/helium-tanks/<id>", methods=["GET"])
@require_roles("StoreManager", "StoreClerk")
def get_tank(id):
    return ok(clean(fetch(db.helium_tanks, id)))


@bp.route("/helium-tanks", methods=["GET"])
@require_roles("StoreManager", "StoreClerk")
def list_tanks():
    limit, offset = parse_limit_offset()
    status = request.args.get("status")
    items = list(db.helium_tanks.values())
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response([clean(x) for x in page], limit, offset, total)


@bp.route("/_helium-tanks/<id>/refill", methods=["POST"])
@require_roles("StoreManager")
def refill_tank(id):
    tank = fetch(db.helium_tanks, id)
    tank["remaining_cubic_ft"] = int(tank["capacity_cubic_ft"])
    tank["status"] = "ACTIVE"
    bump(tank)
    return ok(clean(tank))
