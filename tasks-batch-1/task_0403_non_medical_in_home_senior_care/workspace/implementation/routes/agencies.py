"""Agency endpoints (PRD §3.1)."""
from flask import Blueprint

import db
from middleware import get_auth, require_roles
from response import success
from services import requtil

bp = Blueprint("agencies", __name__)


@bp.post("/agencies")
def create_agency():
    _, role = get_auth()
    require_roles(role, {"AgencyAdmin"})
    body = requtil.get_body()

    name = requtil.require_str(body, "name")
    base_hourly_rate = requtil.require_number(body, "base_hourly_rate")
    live_in_day_rate = requtil.require_number(body, "live_in_day_rate")
    overtime_threshold_hours = requtil.optional_number(body, "overtime_threshold_hours", 40)
    overtime_multiplier = requtil.optional_number(body, "overtime_multiplier", 1.5)
    mileage_rate = requtil.optional_number(body, "mileage_rate", 0.70)
    evv_rounding_minutes = requtil.optional_int(body, "evv_rounding_minutes", 15)
    travel_buffer_minutes = requtil.optional_int(body, "travel_buffer_minutes", 30)

    # Well-formedness bounds (PRD §2.7).
    if base_hourly_rate <= 0:
        raise requtil.invalid("base_hourly_rate must be > 0")
    if live_in_day_rate <= 0:
        raise requtil.invalid("live_in_day_rate must be > 0")
    if overtime_threshold_hours < 0:
        raise requtil.invalid("overtime_threshold_hours must be >= 0")
    if overtime_multiplier < 1:
        raise requtil.invalid("overtime_multiplier must be >= 1")
    if mileage_rate < 0:
        raise requtil.invalid("mileage_rate must be >= 0")
    if evv_rounding_minutes <= 0:
        raise requtil.invalid("evv_rounding_minutes must be > 0")
    if travel_buffer_minutes < 0:
        raise requtil.invalid("travel_buffer_minutes must be >= 0")

    agency = {
        "name": name,
        "base_hourly_rate": base_hourly_rate,
        "live_in_day_rate": live_in_day_rate,
        "overtime_threshold_hours": overtime_threshold_hours,
        "overtime_multiplier": overtime_multiplier,
        "mileage_rate": mileage_rate,
        "evv_rounding_minutes": evv_rounding_minutes,
        "travel_buffer_minutes": travel_buffer_minutes,
    }
    db.stamp_new(agency)
    db.agencies[agency["id"]] = agency
    return success(db.public(agency), status=201)
