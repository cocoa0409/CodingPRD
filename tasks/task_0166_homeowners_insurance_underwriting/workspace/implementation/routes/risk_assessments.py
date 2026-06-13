"""RiskAssessment routes (PRD §3.2)."""
from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_roles
from response import success
from services.calc import wildfire_score, wind_hail_tier
from services.common import (
    get_json_body, require_field, as_int, as_number, as_enum,
    get_or_404, parse_pagination, paginate,
)
from services.models import base_record, serialize

bp = Blueprint("risk_assessments", __name__)

FLOOD_ZONES = {"X", "A", "AE", "VE"}


@bp.post("/risk-assessments")
@require_roles("Underwriter")
def create_risk_assessment():
    body = get_json_body()
    property_id = require_field(body, "property_id")
    fuel = as_int(require_field(body, "wildfire_fuel_density"), "wildfire_fuel_density")
    if not (0 <= fuel <= 100):
        raise err("ERR_INVALID_REQUEST", "wildfire_fuel_density must be 0..100.")
    slope = as_int(require_field(body, "slope_grade_pct"), "slope_grade_pct")
    if not (0 <= slope <= 100):
        raise err("ERR_INVALID_REQUEST", "slope_grade_pct must be 0..100.")
    space = as_int(require_field(body, "defensible_space_ft"), "defensible_space_ft")
    if space < 0:
        raise err("ERR_INVALID_REQUEST", "defensible_space_ft must be >= 0.")
    flood_zone = as_enum(require_field(body, "flood_zone"), "flood_zone", FLOOD_ZONES)
    distance = as_number(require_field(body, "distance_to_coast_mi"), "distance_to_coast_mi")
    if distance < 0:
        raise err("ERR_INVALID_REQUEST", "distance_to_coast_mi must be >= 0.")

    with db.lock:
        # existence: property_id (body) must resolve (§2.5 left-to-right; only id here)
        get_or_404("property", property_id)
        rec = base_record()
        rec.update({
            "property_id": property_id,
            "wildfire_fuel_density": fuel,
            "slope_grade_pct": slope,
            "defensible_space_ft": space,
            "flood_zone": flood_zone,
            "distance_to_coast_mi": distance,
            "score_stage": "PROVISIONAL",
        })
        rec["wildfire_score"] = wildfire_score(rec, "PROVISIONAL")
        rec["wind_hail_tier"] = wind_hail_tier(distance)
        rec["status"] = "ACTIVE"
        db.risk_assessments[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.get("/risk-assessments")
@require_roles("Admin", "Agent", "Underwriter")
def list_risk_assessments():
    limit, offset = parse_pagination()
    property_id = request.args.get("property_id")
    with db.lock:
        items = list(db.risk_assessments.values())
        if property_id is not None:
            items = [r for r in items if r["property_id"] == property_id]
        window, meta = paginate(items, limit, offset)
        data = [serialize(r) for r in window]
    return success(data, status=200, list_meta=meta)


@bp.get("/risk-assessments/<rid>")
@require_roles("Admin", "Agent", "Underwriter")
def get_risk_assessment(rid):
    with db.lock:
        rec = get_or_404("risk_assessment", rid)
        return success(serialize(rec), status=200)
