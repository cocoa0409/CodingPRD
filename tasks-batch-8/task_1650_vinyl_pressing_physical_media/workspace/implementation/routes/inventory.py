"""InventoryLot endpoints."""

import math

from flask import Blueprint, request

import db
import serializers
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVENTORY_LOT_NOT_FOUND,
    ERR_RELEASE_NOT_FOUND,
)
from middleware import get_auth, require_role, get_pagination, apply_pagination
from response import success_object, success_list
from services import scheduling, allocations
from services.constants import ZONES, UNITS_PER_PALLET
from .releases import valid_date_str

bp = Blueprint("inventory", __name__)


def get_lot_or_404(lot_id):
    lot = db.inventory_lots.get(lot_id)
    if not lot:
        raise ApiError(ERR_INVENTORY_LOT_NOT_FOUND, "Inventory lot id does not exist", 404)
    return lot


@bp.route("/inventory-lots", methods=["POST"])
def create_inventory_lot():
    _, role = get_auth()
    require_role(role, ["WarehouseManager"])
    body = request.get_json(silent=True) or {}

    release_id = body.get("release_id")
    zone = body.get("zone")

    if not isinstance(release_id, str) or not release_id:
        raise ApiError(ERR_INVALID_REQUEST, "release_id is required", 400)
    release = db.releases.get(release_id)
    if not release:
        raise ApiError(ERR_RELEASE_NOT_FOUND, "release_id does not exist", 404)
    if zone not in ZONES:
        raise ApiError(ERR_INVALID_REQUEST, "zone must be A, B, or C", 400)

    now = db.timestamp_now()
    lot = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "release_id": release_id,
        "zone": zone,
        "receipt_seq": db.next_receipt_seq(release_id),
        "on_hand_units": 0,
        "allocated_units": 0,
        "shipped_units_cum": 0,
        "damaged_units_cum": 0,
        "received_units_cum": 0,
        "storage_daily_accrual_cents": 0,
        "storage_monthly_statement_cents": 0,
        "_receive_events": [],
        "_daily_on_hand": {},
    }
    db.inventory_lots[lot["id"]] = lot
    return success_object(serializers.inventory_lot(lot), 201)


@bp.route("/inventory-lots", methods=["GET"])
def list_inventory_lots():
    get_auth()
    limit, offset = get_pagination()
    release_id = request.args.get("release_id")
    zone = request.args.get("zone")
    items = list(db.inventory_lots.values())
    if release_id is not None:
        items = [l for l in items if l["release_id"] == release_id]
    if zone is not None:
        items = [l for l in items if l["zone"] == zone]
    page, total = apply_pagination(items, limit, offset)
    return success_list([serializers.inventory_lot(l) for l in page], limit, offset, total)


@bp.route("/inventory-lots/<lid>", methods=["GET"])
def get_inventory_lot(lid):
    get_auth()
    return success_object(serializers.inventory_lot(get_lot_or_404(lid)))


@bp.route("/inventory-lots/<lid>/stock-events", methods=["POST"])
def stock_event(lid):
    _, role = get_auth()
    require_role(role, ["WarehouseManager"])
    lot = get_lot_or_404(lid)
    body = request.get_json(silent=True) or {}

    event = body.get("event")
    quantity = body.get("quantity")
    event_date = body.get("event_date")

    if event not in ("RECEIVE", "DAMAGE_WRITE_OFF"):
        raise ApiError(ERR_INVALID_REQUEST, "event must be RECEIVE or DAMAGE_WRITE_OFF", 400)
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "quantity must be a positive integer", 400)
    if event_date is not None and not valid_date_str(event_date):
        raise ApiError(ERR_INVALID_REQUEST, "event_date must be yyyy-mm-dd", 400)

    release = db.releases[lot["release_id"]]

    if event == "RECEIVE":
        eff_date = event_date or db.today_logical().isoformat()
        upp = UNITS_PER_PALLET[release["format"]]
        pallets = math.ceil(quantity / upp)
        scheduling.zone_receiving_check(release, lot["zone"], quantity, eff_date)
        lot["on_hand_units"] += quantity
        lot["received_units_cum"] += quantity
        lot["_receive_events"].append((eff_date, pallets))
        lot["_daily_on_hand"][db.today_logical().isoformat()] = lot["on_hand_units"]
        lot["version"] += 1
        lot["updated_at"] = db.timestamp_now()
        allocations.backorder_sweep(release["id"])
    else:  # DAMAGE_WRITE_OFF
        if quantity > lot["on_hand_units"]:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "DAMAGE_WRITE_OFF quantity may not exceed on_hand_units",
                400,
            )
        lot["on_hand_units"] -= quantity
        lot["damaged_units_cum"] += quantity
        lot["_daily_on_hand"][db.today_logical().isoformat()] = lot["on_hand_units"]
        lot["version"] += 1
        lot["updated_at"] = db.timestamp_now()

    return success_object(serializers.inventory_lot(lot))
