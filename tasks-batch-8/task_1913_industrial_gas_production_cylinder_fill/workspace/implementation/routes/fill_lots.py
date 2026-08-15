"""FillLot endpoints (PRD §3.3)."""
from flask import Blueprint

from constants import MIN_TANK_RESERVE_LITERS, PRODUCTS
from db import store
from errors import (
    ERR_CYLINDER_NOT_AVAILABLE,
    ERR_FILL_LOT_INVALID_STATE,
    ERR_HYDRO_RETEST_OVERDUE,
    ERR_LOT_HAS_NO_CYLINDERS,
    ERR_PLANT_NOT_OPERATING,
    ERR_PRODUCT_SERVICE_MISMATCH,
    ERR_TANK_LEVEL_TOO_LOW,
    ERR_TANK_NOT_IN_SERVICE,
    ApiError,
    bad_request,
    not_found,
)
from middleware import ANY_ROLE, get_body, locked, req_enum, req_int, req_str, require_roles
from response import success
from routes.listing import list_response
from services import calc
from services.ops import base_record, cylinder_out, fill_lot_out
from util import dec, is_num, touch

bp = Blueprint("fill_lots", __name__)


def _get_lot(fillLotId):
    lot = store.fill_lots.get(fillLotId)
    if lot is None:
        not_found("fill lot not found")
    return lot


def _plant_of_lot(lot):
    tank = store.tanks.get(lot["tank_id"])
    if tank is None:
        return None
    return store.plants.get(tank["plant_id"])


@bp.post("/api/fill-lots")
@locked
def create_fill_lot():
    require_roles("ProductionOperator")
    body = get_body()
    tank_id = req_str(body, "tank_id")
    product = req_enum(body, "product_code", PRODUCTS)
    target = req_int(body, "target_fill_pressure_bar")
    if target <= 0:
        bad_request("target_fill_pressure_bar must be > 0")
    tank = store.tanks.get(tank_id)
    if tank is None:
        not_found("tank not found")
    if tank["product_code"] != product:
        raise ApiError(ERR_PRODUCT_SERVICE_MISMATCH, 422, "product_code must equal the tank's product_code")
    lot = base_record()
    lot.update(
        {
            "tank_id": tank_id,
            "product_code": product,
            "target_fill_pressure_bar": target,
            "draw_estimate_liters": dec(0),
            "draw_actual_liters": None,
            "completed_by_user_id": None,
            "status": "PLANNED",
            "reservation_outstanding": False,
        }
    )
    store.fill_lots[lot["id"]] = lot
    return success(fill_lot_out(lot), status=201)


@bp.get("/api/fill-lots")
@locked
def list_fill_lots():
    require_roles(*ANY_ROLE)
    return list_response(
        store.fill_lots.values(), fill_lot_out, [("tank_id", "tank_id"), ("status", "status")]
    )


@bp.get("/api/fill-lots/<fillLotId>")
@locked
def get_fill_lot(fillLotId):
    require_roles(*ANY_ROLE)
    return success(fill_lot_out(_get_lot(fillLotId)))


@bp.post("/api/fill-lots/<fillLotId>/cylinders")
@locked
def assign_cylinder(fillLotId):
    require_roles("ProductionOperator")
    body = get_body()
    cylinder_id = req_str(body, "cylinder_id")
    lot = _get_lot(fillLotId)
    c = store.cylinders.get(cylinder_id)
    if c is None:
        not_found("cylinder not found")
    if lot["status"] != "PLANNED":
        raise ApiError(ERR_FILL_LOT_INVALID_STATE, 409, "lot must be PLANNED to accept cylinders")
    if c["status"] != "IN_STOCK":
        raise ApiError(ERR_CYLINDER_NOT_AVAILABLE, 409, "cylinder must be IN_STOCK")
    if calc.hydro_status(c) == "OVERDUE":
        raise ApiError(ERR_HYDRO_RETEST_OVERDUE, 422, "cylinder hydrostatic retest is overdue")
    if c["service_gas"] != lot["product_code"]:
        raise ApiError(ERR_PRODUCT_SERVICE_MISMATCH, 422, "cylinder service_gas must equal the lot product_code")
    c["status"] = "RESERVED"
    c["current_fill_lot_id"] = lot["id"]
    touch(c)
    lot["draw_estimate_liters"] = calc.fill_draw_liters(lot)
    touch(lot)
    return success(cylinder_out(c), status=201)


@bp.post("/api/fill-lots/<fillLotId>/start-fill")
@locked
def start_fill(fillLotId):
    require_roles("ProductionOperator")
    get_body()
    lot = _get_lot(fillLotId)
    tank = store.tanks[lot["tank_id"]]
    plant = _plant_of_lot(lot)
    if plant is None or plant["status"] != "OPERATING":
        raise ApiError(ERR_PLANT_NOT_OPERATING, 409, "plant is not OPERATING")
    if tank["status"] != "IN_SERVICE":
        raise ApiError(ERR_TANK_NOT_IN_SERVICE, 409, "tank is not IN_SERVICE")
    if lot["status"] != "PLANNED":
        raise ApiError(ERR_FILL_LOT_INVALID_STATE, 409, "lot must be PLANNED to start filling")
    if not calc.lot_reserved_cylinders(lot):
        raise ApiError(ERR_LOT_HAS_NO_CYLINDERS, 409, "lot has no RESERVED cylinders")
    headroom = calc.tank_current_level(tank) - tank["reserved_liters"]
    if headroom < lot["draw_estimate_liters"] + MIN_TANK_RESERVE_LITERS:
        raise ApiError(ERR_TANK_LEVEL_TOO_LOW, 409, "insufficient tank headroom for the estimated draw")
    tank["reserved_liters"] += lot["draw_estimate_liters"]
    lot["reservation_outstanding"] = True
    lot["status"] = "FILLING"
    touch(lot)
    touch(tank)
    return success(fill_lot_out(lot))


@bp.post("/api/fill-lots/<fillLotId>/complete-fill")
@locked
def complete_fill(fillLotId):
    uid, _ = require_roles("ProductionOperator")
    body = get_body()
    raw = body.get("measured_residuals")
    if raw is None or not isinstance(raw, list):
        bad_request("measured_residuals must be an array")
    residuals = {}
    for entry in raw:
        if not isinstance(entry, dict):
            bad_request("measured_residuals entries must be objects")
        cid = entry.get("cylinder_id")
        rp = entry.get("residual_pressure_bar")
        if not isinstance(cid, str) or not is_num(rp):
            bad_request("each measured_residuals entry needs cylinder_id and residual_pressure_bar")
        residuals[cid] = dec(rp)
    lot = _get_lot(fillLotId)
    plant = _plant_of_lot(lot)
    if plant is None or plant["status"] != "OPERATING":
        raise ApiError(ERR_PLANT_NOT_OPERATING, 409, "plant is not OPERATING")
    if lot["status"] != "FILLING":
        raise ApiError(ERR_FILL_LOT_INVALID_STATE, 409, "lot must be FILLING to complete")
    tank = store.tanks[lot["tank_id"]]
    actual = calc.fill_draw_liters(lot, residuals=residuals)
    if lot["reservation_outstanding"]:
        tank["reserved_liters"] -= lot["draw_estimate_liters"]
        lot["reservation_outstanding"] = False
    tank["drawn_liters"] += actual
    lot["draw_actual_liters"] = actual
    lot["completed_by_user_id"] = uid
    lot["status"] = "AWAITING_ANALYSIS"
    touch(lot)
    touch(tank)
    return success(fill_lot_out(lot))


@bp.post("/api/fill-lots/<fillLotId>/rework")
@locked
def rework(fillLotId):
    require_roles("ProductionOperator")
    get_body()
    lot = _get_lot(fillLotId)
    if lot["status"] != "ANALYSIS_FAILED":
        raise ApiError(ERR_FILL_LOT_INVALID_STATE, 409, "lot must be ANALYSIS_FAILED to rework")
    plant = _plant_of_lot(lot)
    if plant is None or plant["status"] != "OPERATING":
        raise ApiError(ERR_PLANT_NOT_OPERATING, 409, "plant is not OPERATING")
    for c in store.cylinders.values():
        if c["status"] == "QUARANTINED" and c["current_fill_lot_id"] == lot["id"]:
            c["status"] = "RESERVED"
            touch(c)
    lot["status"] = "FILLING"
    touch(lot)
    return success(fill_lot_out(lot))


@bp.post("/api/fill-lots/<fillLotId>/vent")
@locked
def vent(fillLotId):
    require_roles("ProductionOperator")
    get_body()
    lot = _get_lot(fillLotId)
    if lot["status"] not in ("PLANNED", "FILLING", "AWAITING_ANALYSIS", "ANALYSIS_FAILED"):
        raise ApiError(ERR_FILL_LOT_INVALID_STATE, 409, "lot cannot be vented from its current state")
    tank = store.tanks[lot["tank_id"]]
    touched_tank = False
    if lot["status"] == "FILLING":
        if lot["reservation_outstanding"]:
            tank["reserved_liters"] -= lot["draw_estimate_liters"]
            lot["reservation_outstanding"] = False
            touched_tank = True
    elif lot["status"] in ("AWAITING_ANALYSIS", "ANALYSIS_FAILED"):
        if lot["draw_actual_liters"] is not None:
            tank["drawn_liters"] -= lot["draw_actual_liters"]
            touched_tank = True
    for c in store.cylinders.values():
        if c["current_fill_lot_id"] == lot["id"] and c["status"] in ("RESERVED", "QUARANTINED"):
            c["status"] = "IN_STOCK"
            c["current_fill_lot_id"] = None
            touch(c)
    lot["status"] = "VENTED"
    touch(lot)
    if touched_tank:
        touch(tank)
    return success(fill_lot_out(lot))


@bp.post("/api/fill-lots/<fillLotId>/recall")
@locked
def recall(fillLotId):
    require_roles("QualityManager")
    get_body()
    lot = _get_lot(fillLotId)
    if lot["status"] != "RELEASED":
        raise ApiError(ERR_FILL_LOT_INVALID_STATE, 409, "lot must be RELEASED to recall")
    touched = set()
    quarantined_cylinders = set()
    for c in store.cylinders.values():
        if c["last_fill_lot_id"] == lot["id"] and c["status"] in ("FILLED", "ON_RENT"):
            c["status"] = "QUARANTINED"
            touch(c)
            touched.add(c["id"])
            quarantined_cylinders.add(c["id"])
    held_customers = set()
    for r in store.rentals.values():
        if r["status"] in ("ACTIVE", "OVERDUE") and r["cylinder_id"] in quarantined_cylinders:
            r["status"] = "RECALL_HOLD"
            touch(r)
            touched.add(r["id"])
            held_customers.add(r["customer_id"])
    for cid in held_customers:
        cust = store.customers.get(cid)
        if cust is not None and not cust["recall_flag"]:
            cust["recall_flag"] = True
            touch(cust)
            touched.add(cid)
    lot["status"] = "RECALLED"
    touch(lot)
    return success(fill_lot_out(lot))
