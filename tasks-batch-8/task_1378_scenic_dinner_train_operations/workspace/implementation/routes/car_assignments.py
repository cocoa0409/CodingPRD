"""Car assignments: build a DRAFT excursion's consist car by car; each addition
snapshots effective_capacity and increments the excursion's version."""
from flask import Blueprint, request

import db
from auth import ALL_ROLES, require_roles
from db import new_entity, public, touch
from envelope import success_list, success_obj
from errors import (
    ApiError,
    ERR_CLASS_STOCK_MISMATCH,
    ERR_INVALID_REFERENCE,
    ERR_INVALID_STATE,
    ERR_MAINTENANCE_WINDOW_CONFLICT,
    ERR_NOT_FOUND,
    ERR_STOCK_ALREADY_ASSIGNED,
    ERR_STOCK_COMMITTED,
    ERR_STOCK_OUT_OF_SERVICE,
    ERR_STOCK_UNAVAILABLE,
    ERR_VALIDATION,
)
from services.core import (
    STOCK_CLASS_MAP,
    stock_has_wo_on_date,
    stock_on_other_excursion_same_date,
)
from validators import body, paginate, pagination, req_enum, req_int, req_str

bp = Blueprint("car_assignments", __name__)

CLASS_CODES = ("LOCO", "COACH", "FIRST_CLASS", "DINING")


def get_assignment_or_404(ca_id):
    ca = db.car_assignments.get(ca_id)
    if ca is None:
        raise ApiError(ERR_NOT_FOUND, "Car assignment not found", 404)
    return ca


@bp.post("/railroad/car-assignments")
def create_car_assignment():
    require_roles("Scheduler")
    data = body()
    excursion_id = req_str(data, "excursion_id")
    # Tier 4: consist edits only while the excursion is DRAFT.
    exc = db.excursions.get(excursion_id)
    if exc is not None and exc["status"] != "DRAFT":
        raise ApiError(
            ERR_INVALID_STATE,
            "Consist edits require the excursion to be DRAFT",
            409,
        )
    stock_id = req_str(data, "stock_id")
    class_code = req_enum(data, "class_code", CLASS_CODES)
    position = req_int(data, "position")
    if position < 1:
        raise ApiError(ERR_VALIDATION, "position must be at least 1", 400)
    # Tier 7: body FK existence.
    if exc is None:
        raise ApiError(ERR_INVALID_REFERENCE, "excursion_id does not exist", 422)
    stock = db.rolling_stock.get(stock_id)
    if stock is None:
        raise ApiError(ERR_INVALID_REFERENCE, "stock_id does not exist", 422)
    # Tier 5: referenced stock-state gates.
    if stock["status"] == "IN_MAINTENANCE":
        raise ApiError(ERR_STOCK_UNAVAILABLE, "Stock unit is IN_MAINTENANCE", 409)
    if stock["status"] == "OUT_OF_SERVICE":
        raise ApiError(
            ERR_STOCK_OUT_OF_SERVICE, "Operation targets a retired stock unit", 409
        )
    # Tier 8b: class_code vs stock_type compatibility.
    if STOCK_CLASS_MAP[stock["stock_type"]] != class_code:
        raise ApiError(
            ERR_CLASS_STOCK_MISMATCH,
            "class_code is incompatible with the unit's stock_type",
            422,
        )
    # Tier 8c: no duplicate unit; unique position within the excursion.
    for ca in db.car_assignments.values():
        if ca["excursion_id"] != exc["id"]:
            continue
        if ca["stock_id"] == stock["id"]:
            raise ApiError(
                ERR_STOCK_ALREADY_ASSIGNED,
                "Unit is already in this excursion's consist",
                409,
            )
        if ca["position"] == position:
            raise ApiError(
                ERR_VALIDATION,
                "position must be unique within the excursion",
                400,
            )
    # Tier 9d: maintenance-window mirror on the excursion's service_date.
    if stock_has_wo_on_date(stock["id"], exc["service_date"]):
        raise ApiError(
            ERR_MAINTENANCE_WINDOW_CONFLICT,
            "Unit has a maintenance window intersecting the service date",
            409,
        )
    # Tier 9e: unit already committed to another excursion on the same date.
    if stock_on_other_excursion_same_date(stock["id"], exc["id"], exc["service_date"]):
        raise ApiError(
            ERR_STOCK_COMMITTED,
            "Unit is already assigned to another excursion on this service date",
            409,
        )
    ca = new_entity(
        {
            "excursion_id": exc["id"],
            "stock_id": stock["id"],
            "class_code": class_code,
            "position": position,
            "effective_capacity": stock["seat_capacity"],
        }
    )
    db.car_assignments[ca["id"]] = ca
    # Every consist change increments the excursion's version.
    touch(exc)
    return success_obj(public(ca), 201)


@bp.get("/railroad/car-assignments/<cid>")
def get_car_assignment(cid):
    require_roles(*ALL_ROLES)
    return success_obj(public(get_assignment_or_404(cid)), 200)


@bp.get("/railroad/car-assignments")
def list_car_assignments():
    require_roles(*ALL_ROLES)
    items = list(db.car_assignments.values())
    excursion_id = request.args.get("excursion_id")
    stock_id = request.args.get("stock_id")
    if excursion_id is not None:
        items = [c for c in items if c["excursion_id"] == excursion_id]
    if stock_id is not None:
        items = [c for c in items if c["stock_id"] == stock_id]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([public(c) for c in page], limit, offset, total)
