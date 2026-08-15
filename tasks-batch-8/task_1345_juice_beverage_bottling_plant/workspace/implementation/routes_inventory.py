"""FinishedGoodLot and WarehouseZone endpoints."""
from flask import Blueprint, request

from domain import TEMP_CLASSES, ser_fg_lot, ser_zone
from errors import err
from routes_runs import get_zone_or_404
from services import deallocate_lot_from_open_orders
from store import db, stamp, touch
from util import body, ok, paginate, req_enum, req_field, require_any, require_roles

bp = Blueprint("inventory", __name__)


def get_lot_or_404(lot_id):
    lot = db.fg_lots.get(lot_id)
    if lot is None:
        raise err("ERR_LOT_NOT_FOUND", f"FinishedGoodLot {lot_id} not found")
    return lot


@bp.get("/v1/finished-good-lots")
def list_lots():
    require_any()
    formula_id = request.args.get("formula_id")
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    items = list(db.fg_lots.values())
    if formula_id is not None:
        items = [l for l in items if l["formula_id"] == formula_id]
    if customer_id is not None:
        items = [l for l in items if l["customer_id"] == customer_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    return paginate(items, ser_fg_lot)


@bp.get("/v1/finished-good-lots/<lot_id>")
def get_lot(lot_id):
    require_any()
    return ok(ser_fg_lot(get_lot_or_404(lot_id)))


@bp.post("/v1/finished-good-lots/<lot_id>/recall")
def recall_lot(lot_id):
    require_roles("QAInspector")
    lot = get_lot_or_404(lot_id)
    if lot["status"] not in ("AVAILABLE", "EXPIRED"):
        raise err("ERR_LOT_STATE_INVALID", "recall requires status AVAILABLE or EXPIRED")
    if lot["status"] == "AVAILABLE":
        deallocate_lot_from_open_orders(lot)
    lot["status"] = "RECALLED"
    touch(lot)
    return ok(ser_fg_lot(lot))


@bp.post("/v1/warehouse-zones")
def create_zone():
    require_roles("PlantManager")
    data = body()
    zone_code = req_field(data, "zone_code", "str")
    temperature_class = req_enum(data, "temperature_class", TEMP_CLASSES)
    pallet_capacity = req_field(data, "pallet_capacity", "int")
    zone = {
        "zone_code": zone_code,
        "temperature_class": temperature_class,
        "pallet_capacity": pallet_capacity,
    }
    stamp(zone)
    db.zones[zone["id"]] = zone
    return ok(ser_zone(zone), 201)


@bp.get("/v1/warehouse-zones")
def list_zones():
    require_any()
    return paginate(list(db.zones.values()), ser_zone)


@bp.get("/v1/warehouse-zones/<zone_id>")
def get_zone(zone_id):
    require_any()
    return ok(ser_zone(get_zone_or_404(zone_id)))


@bp.get("/v1/warehouse-zones/<zone_id>/finished-good-lots")
def zone_lots(zone_id):
    require_any()
    get_zone_or_404(zone_id)
    items = [l for l in db.fg_lots.values() if l["warehouse_zone_id"] == zone_id]
    return paginate(items, ser_fg_lot)
