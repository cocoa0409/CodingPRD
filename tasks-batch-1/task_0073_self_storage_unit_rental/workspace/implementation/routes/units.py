from flask import Blueprint, request

import errors
from errors import err
from db import db
from models import make_common, serialize
from middleware import get_identity, require_role
from helpers import get_json_body, lookup, parse_pagination, paginate, sort_by_created, as_str
from response import success, list_response

bp = Blueprint("units", __name__)

SIZE_CLASSES = {"SIZE_5X5", "SIZE_10X10", "SIZE_10X20"}


@bp.post("/units")
def create_unit():
    _, role = get_identity()
    require_role(role, {"FacilityManager"})
    body = get_json_body()

    facility_id = body.get("facility_id")
    if not isinstance(facility_id, str) or not facility_id:
        raise err(errors.ERR_INVALID_REQUEST, "facility_id is required")
    facility = lookup(db.facilities, facility_id, "facility")

    unit_number = body.get("unit_number")
    size_class = body.get("size_class")
    monthly_rate_cents = body.get("monthly_rate_cents")
    climate_controlled = body.get("climate_controlled", False)

    if not isinstance(unit_number, str) or not unit_number:
        raise err(errors.ERR_INVALID_REQUEST, "unit_number is required")
    if size_class not in SIZE_CLASSES:
        raise err(errors.ERR_INVALID_REQUEST, "size_class must be one of SIZE_5X5, SIZE_10X10, SIZE_10X20")
    if isinstance(monthly_rate_cents, bool) or not isinstance(monthly_rate_cents, int):
        raise err(errors.ERR_INVALID_REQUEST, "monthly_rate_cents must be an integer")
    if monthly_rate_cents <= 0:
        raise err(errors.ERR_INVALID_REQUEST, "monthly_rate_cents must be > 0")
    if not isinstance(climate_controlled, bool):
        raise err(errors.ERR_INVALID_REQUEST, "climate_controlled must be a boolean")

    # Duplicate unit_number within facility.
    for u in db.units.values():
        if u["facility_id"] == facility_id and u["unit_number"] == unit_number:
            raise err(errors.ERR_DUPLICATE_UNIT_NUMBER, "unit_number already used in this facility")

    unit = make_common()
    unit.update({
        "facility_id": facility_id,
        "unit_number": unit_number,
        "size_class": size_class,
        "climate_controlled": climate_controlled,
        "monthly_rate_cents": monthly_rate_cents,
        "status": "AVAILABLE",
        "current_lease_id": None,
    })
    db.units[unit["id"]] = unit
    return success(serialize(unit), 201)


@bp.get("/units/<unit_id>")
def get_unit(unit_id):
    get_identity()
    unit = lookup(db.units, unit_id, "unit")
    return success(serialize(unit), 200)


@bp.get("/units")
def list_units():
    get_identity()
    limit, offset = parse_pagination()
    facility_id = request.args.get("facility_id")
    status = request.args.get("status")
    current_lease_id = request.args.get("current_lease_id")

    items = list(db.units.values())
    if facility_id is not None:
        items = [u for u in items if u["facility_id"] == facility_id]
    if status is not None:
        items = [u for u in items if u["status"] == status]
    if current_lease_id is not None:
        items = [u for u in items if u["current_lease_id"] == current_lease_id]

    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_response([serialize(u) for u in page], total, limit, offset)
