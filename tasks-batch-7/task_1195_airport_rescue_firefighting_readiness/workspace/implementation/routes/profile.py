"""Logical clock, singleton airport profile, and the readiness detail view."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

from db import store, base_entity, serialize, parse_dt
from errors import (
    ApiError, ERR_PROFILE_NOT_FOUND, ERR_PROFILE_ALREADY_EXISTS, ERR_VALIDATION_FAILED,
)
from middleware import require, json_body, need_str, need_enum, ALL_ROLES
from response import success
from services import calc

bp = Blueprint("profile", __name__)


@bp.post("/arff/_clock/set_current_utc")
def set_clock():
    require(["AirportManager"])
    data = json_body()
    raw = data.get("to_iso8601")
    dt = parse_dt(raw)
    if dt is None:
        raise ApiError(ERR_VALIDATION_FAILED, 400,
                       "'to_iso8601' is required and must be an ISO 8601 timestamp")
    store.clock = dt
    store.clock_raw = raw
    calc.apply_time_derived()
    return success({"current_utc": store.clock_raw}, "object", 200)


@bp.post("/arff/airport-profile")
def create_profile():
    require(["AirportManager"])
    data = json_body()
    code = need_str(data, "airport_code", nonempty=True)
    cert = need_enum(data, "certificated_index", calc.INDEXES)
    if store.profile is not None:
        raise ApiError(ERR_PROFILE_ALREADY_EXISTS, 409,
                       "The singleton airport profile already exists")
    p = base_entity()
    p.update({
        "airport_code": code,
        "certificated_index": cert,
        "required_index_by_aircraft": None,
        "supported_index_by_equipment": None,
        "supported_index_by_staffing": None,
        "effective_index": None,
        "index_compliance_status": None,
    })
    store.profile = p
    # Initial recompute: notification create rule suppressed (no prior value);
    # version stays 1 at creation.
    calc.recompute_profile(bump="never")
    return success(serialize(p), "object", 201)


def _profile_or_404():
    if store.profile is None:
        raise ApiError(ERR_PROFILE_NOT_FOUND, 404, "Airport profile not yet created")
    return store.profile


@bp.get("/arff/airport-profile")
def get_profile():
    require(ALL_ROLES)
    return success(serialize(_profile_or_404()), "object", 200)


@bp.get("/arff/airport-profile/readiness")
def get_readiness():
    require(ALL_ROLES)
    p = _profile_or_404()
    fleet = calc.measured_fleet()
    water_sum, chem_sum = calc.fleet_sums(fleet, rated=False)
    cert = p["certificated_index"]
    eff = calc.effective_water(water_sum, chem_sum, cert)
    eff_q = eff.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    open_n = calc.open_notification()
    data = {
        "certificated_index": cert,
        "required_index_by_aircraft": p["required_index_by_aircraft"],
        "supported_index_by_equipment": p["supported_index_by_equipment"],
        "supported_index_by_staffing": p["supported_index_by_staffing"],
        "effective_index": p["effective_index"],
        "index_compliance_status": p["index_compliance_status"],
        "rated_basis_supported_index": calc.compute_supported_index_by_equipment(rated=True),
        "roster_basis_supported_index": calc.compute_supported_index_by_staffing(roster=True),
        "effective_water_gal_at_certificated_index": float(eff_q),
        "in_service_passing_vehicle_count": len(fleet),
        "roster_active_count": len(calc.roster_active()),
        "deployment_ready_count": len(calc.deployment_ready()),
        "open_notification_id": open_n["id"] if open_n is not None else None,
    }
    return success(data, "object", 200)
