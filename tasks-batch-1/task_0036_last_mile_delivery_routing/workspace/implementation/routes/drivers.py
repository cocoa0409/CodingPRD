from flask import Blueprint

from db import db, now_iso
from middleware import require_roles
from response import success_object, success_array
from services.common import (
    get_json_body, parse_pagination, paginate,
    require_str, opt_bool, require_number_positive,
    get_driver_or_404,
)
from services.serialize import serialize_driver, serialize_route

bp = Blueprint("drivers", __name__)


@bp.post("/delivery/drivers")
@require_roles("DispatchManager")
def create_driver():
    body = get_json_body()
    name = require_str(body, "name")
    hazmat = opt_bool(body, "hazmat_certified", False)
    capacity = require_number_positive(body, "vehicle_capacity_kg")
    ts = now_iso()
    did = db.new_id()
    driver = {
        "id": did,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "name": name,
        "hazmat_certified": hazmat,
        "vehicle_capacity_kg": capacity,
        "failure_points": 0,
        "status": "ACTIVE",
    }
    db.drivers[did] = driver
    return success_object(serialize_driver(driver), 201)


@bp.get("/delivery/drivers")
@require_roles("DispatchManager", "CustomerServiceAgent")
def list_drivers():
    limit, offset = parse_pagination()
    items = sorted(db.drivers.values(), key=lambda d: (d["created_at"], d["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return success_array([serialize_driver(d) for d in page], limit, offset, total)


@bp.get("/delivery/drivers/<driver_id>")
@require_roles("DispatchManager", "Driver", "CustomerServiceAgent")
def get_driver(driver_id):
    driver = get_driver_or_404(driver_id)
    return success_object(serialize_driver(driver), 200)


@bp.post("/delivery/drivers/<driver_id>/suspend")
@require_roles("DispatchManager")
def suspend_driver(driver_id):
    driver = get_driver_or_404(driver_id)
    driver["status"] = "SUSPENDED"
    driver["updated_at"] = now_iso()
    driver["version"] += 1
    return success_object(serialize_driver(driver), 200)


@bp.get("/delivery/drivers/<driver_id>/routes")
@require_roles("DispatchManager", "Driver")
def list_driver_routes(driver_id):
    get_driver_or_404(driver_id)
    limit, offset = parse_pagination()
    items = [r for r in db.routes.values() if r["driver_id"] == driver_id]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return success_array([serialize_route(r) for r in page], limit, offset, total)
