"""HousingUnit routes."""
from flask import Blueprint, request

from common import (
    get_housing_unit_or_404,
    get_json_body,
    get_program_or_404,
    paginate,
    require_field,
    require_int,
    stamp_new,
)
from db import db
from errors import api_error
from middleware import require_roles
from response import success
from services.calc import APARTMENT_BEDROOMS

bp = Blueprint("housing_units", __name__)


VALID_APARTMENT = set(APARTMENT_BEDROOMS.keys())


@bp.post("/housing-programs/<program_id>/housing-units")
def create_unit(program_id):
    require_roles("HousingDirector")
    get_program_or_404(program_id)
    body = get_json_body()

    unit_code = require_field(body, "unit_code")
    if not isinstance(unit_code, str) or not unit_code.strip():
        raise api_error("ERR_INVALID_REQUEST", "unit_code must be a non-empty string")
    apartment_type = require_field(body, "apartment_type")
    if apartment_type not in VALID_APARTMENT:
        raise api_error("ERR_INVALID_REQUEST", "Invalid apartment_type")
    bedroom_count = require_int(body, "bedroom_count", minimum=0)
    if APARTMENT_BEDROOMS[apartment_type] != bedroom_count:
        raise api_error("ERR_BEDROOM_COUNT_TYPE_MISMATCH",
                        "bedroom_count does not match apartment_type")
    square_meters = require_int(body, "square_meters", minimum=1)
    monthly_base_rent = require_int(body, "monthly_base_rent_cents", minimum=0)
    location_priority = require_int(body, "location_priority_tier",
                                    minimum=1, maximum=5)
    accessibility = body.get("accessibility_compliant")
    if not isinstance(accessibility, bool):
        raise api_error("ERR_INVALID_REQUEST",
                        "accessibility_compliant must be boolean")

    # Uniqueness within program
    for u in db.housing_units.values():
        if u.get("housing_program_id") == program_id and u.get("unit_code") == unit_code:
            raise api_error("ERR_INVALID_REQUEST",
                            "unit_code must be unique within the program")

    unit = {
        "housing_program_id": program_id,
        "unit_code": unit_code,
        "apartment_type": apartment_type,
        "bedroom_count": bedroom_count,
        "square_meters": square_meters,
        "monthly_base_rent_cents": monthly_base_rent,
        "location_priority_tier": location_priority,
        "accessibility_compliant": accessibility,
        "status": "AVAILABLE",
    }
    stamp_new(unit)
    db.housing_units[unit["id"]] = unit
    return success(unit, status=201)


@bp.get("/housing-programs/<program_id>/housing-units")
def list_units(program_id):
    require_roles("HousingDirector", "HousingOfficer", "Applicant", "Citizen",
                  "IntegrationGateway")
    get_program_or_404(program_id)
    status_filter = request.args.get("status")
    apartment_filter = request.args.get("apartment_type")
    items = []
    for u in db.housing_units.values():
        if u.get("housing_program_id") != program_id:
            continue
        if status_filter and u.get("status") != status_filter:
            continue
        if apartment_filter and u.get("apartment_type") != apartment_filter:
            continue
        items.append(u)
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.get("/housing-programs/<program_id>/housing-units/<unit_id>")
def get_unit(program_id, unit_id):
    require_roles("HousingDirector", "HousingOfficer", "Applicant", "Citizen",
                  "IntegrationGateway")
    get_program_or_404(program_id)
    unit = get_housing_unit_or_404(program_id, unit_id)
    return success(unit)
