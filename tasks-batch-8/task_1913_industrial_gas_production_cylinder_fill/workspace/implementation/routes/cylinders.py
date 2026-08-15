"""CylinderAsset endpoints (PRD §3.2)."""
from flask import Blueprint

from constants import (
    CYLINDER_STATUSES,
    DISPOSITIONS,
    PRODUCTS,
    RETEST_RESULTS,
    SIZE_CODES,
    SIZE_SPECS,
)
from db import store
from errors import (
    ERR_CYLINDER_NOT_AVAILABLE,
    ERR_DUPLICATE_CYLINDER_SERIAL,
    ApiError,
    bad_request,
    not_found,
)
from middleware import ANY_ROLE, get_body, locked, req_enum, req_str, require_roles
from response import success
from routes.listing import list_response
from services import calc
from services.ops import base_record, cylinder_out
from util import parse_date, touch

bp = Blueprint("cylinders", __name__)


@bp.post("/api/cylinders")
@locked
def create_cylinder():
    require_roles("ProductionOperator")
    body = get_body()
    serial = req_str(body, "serial_number")
    size_code = req_enum(body, "size_code", SIZE_CODES)
    service_gas = req_enum(body, "service_gas", PRODUCTS)
    last_hydro = parse_date(body.get("last_hydro_date"))
    if last_hydro is None:
        bad_request("last_hydro_date must be an ISO date")
    for c in store.cylinders.values():
        if c["serial_number"] == serial:
            raise ApiError(ERR_DUPLICATE_CYLINDER_SERIAL, 409, "serial_number already registered")
    c = base_record()
    c.update(
        {
            "serial_number": serial,
            "size_code": size_code,
            "service_gas": service_gas,
            "water_capacity_liters": SIZE_SPECS[size_code]["water_capacity_liters"],
            "last_hydro_date_d": last_hydro,
            "hydro_due_date_d": calc.hydro_due_date(last_hydro, service_gas),
            "status": "IN_STOCK",
            "current_fill_lot_id": None,
            "last_fill_lot_id": None,
        }
    )
    store.cylinders[c["id"]] = c
    return success(cylinder_out(c), status=201)


@bp.get("/api/cylinders")
@locked
def list_cylinders():
    require_roles(*ANY_ROLE)
    return list_response(
        store.cylinders.values(),
        cylinder_out,
        [
            ("status", "status"),
            ("service_gas", "service_gas"),
            ("current_fill_lot_id", "current_fill_lot_id"),
            ("last_fill_lot_id", "last_fill_lot_id"),
        ],
    )


@bp.get("/api/cylinders/<cylinderId>")
@locked
def get_cylinder(cylinderId):
    require_roles(*ANY_ROLE)
    c = store.cylinders.get(cylinderId)
    if c is None:
        not_found("cylinder not found")
    return success(cylinder_out(c))


@bp.post("/api/cylinders/<cylinderId>/hydro-retests")
@locked
def hydro_retest(cylinderId):
    require_roles("ProductionOperator")
    body = get_body()
    test_date = parse_date(body.get("test_date"))
    if test_date is None:
        bad_request("test_date must be an ISO date")
    result = req_enum(body, "result", RETEST_RESULTS)
    c = store.cylinders.get(cylinderId)
    if c is None:
        not_found("cylinder not found")
    if c["status"] not in ("IN_STOCK", "QUARANTINED"):
        raise ApiError(ERR_CYLINDER_NOT_AVAILABLE, 409, "cylinder must be IN_STOCK or QUARANTINED")
    if result == "PASS":
        c["last_hydro_date_d"] = test_date
        c["hydro_due_date_d"] = calc.hydro_due_date(test_date, c["service_gas"])
    else:
        c["status"] = "QUARANTINED"
    touch(c)
    return success(cylinder_out(c))


@bp.post("/api/cylinders/<cylinderId>/release-quarantine")
@locked
def release_quarantine(cylinderId):
    require_roles("QualityManager")
    get_body()
    c = store.cylinders.get(cylinderId)
    if c is None:
        not_found("cylinder not found")
    ok = c["status"] == "QUARANTINED"
    if ok and c["current_fill_lot_id"] is not None:
        lot = store.fill_lots.get(c["current_fill_lot_id"])
        ok = lot is None or lot["status"] in ("VENTED", "RECALLED")
    if not ok:
        raise ApiError(ERR_CYLINDER_NOT_AVAILABLE, 409, "cylinder is not releasable from quarantine")
    c["status"] = "IN_STOCK"
    c["current_fill_lot_id"] = None
    touch(c)
    return success(cylinder_out(c))


@bp.post("/api/cylinders/<cylinderId>/decommission")
@locked
def decommission(cylinderId):
    require_roles("QualityManager")
    body = get_body()
    disposition = req_enum(body, "disposition", DISPOSITIONS)
    c = store.cylinders.get(cylinderId)
    if c is None:
        not_found("cylinder not found")
    if c["status"] not in ("IN_STOCK", "QUARANTINED"):
        raise ApiError(ERR_CYLINDER_NOT_AVAILABLE, 409, "cylinder must be IN_STOCK or QUARANTINED")
    c["status"] = disposition
    c["current_fill_lot_id"] = None
    touch(c)
    return success(cylinder_out(c))
