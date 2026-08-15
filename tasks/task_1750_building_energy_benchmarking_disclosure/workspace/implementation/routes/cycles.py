"""Reporting cycle endpoints: create, get, OCC-guarded patch, open, close-filing."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import created, ok
from services import core
from validation import (parse_body, json_object, require_path_entity,
                        is_integer, parse_datetime)

bp = Blueprint("cycles", __name__)

_STD_FIELDS = {
    "property_type": core.PROPERTY_TYPES,
    "median_eui": "number",
    "score_slope": "number",
    "baseline_eui_default": "number",
    "annual_reduction_pct": "number",
    "shortfall_tolerance_pct": "number",
    "fine_rate_cents_per_sqft": "number",
    "performance_fine_cap_cents": "number",
}


def _validate_performance_standards(value):
    if not isinstance(value, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, "performance_standards must be an array")
    for entry in value:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "performance_standards entries must be objects")
        for field, spec in _STD_FIELDS.items():
            if field not in entry:
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               "Missing performance_standards field: %s" % field)
            v = entry[field]
            if field == "property_type":
                if v not in core.PROPERTY_TYPES:
                    raise ApiError("ERR_INVALID_REQUEST", 400,
                                   "performance_standards.property_type is invalid")
            elif not (isinstance(v, (int, float)) and not isinstance(v, bool)):
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               "performance_standards.%s must be a number" % field)


def _validate_covered_property_types(value):
    if not isinstance(value, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, "covered_property_types must be an array")
    for item in value:
        if item not in core.PROPERTY_TYPES:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "covered_property_types entries must be valid property types")


@bp.post("/v1/reporting-cycles")
def create_cycle():
    uid, _ = get_context()
    require_roles(["ComplianceOfficer"])
    body = parse_body({
        "cycle_year": ("integer", True, None),
        "filing_deadline_at": ("datetime", True, None),
        "covered_floor_area_threshold_sqft": ("integer", True, None),
        "covered_property_types": ("list", True, None),
        "late_fine_daily_rate_cents": ("integer", True, None),
        "late_fine_cap_days": ("integer", True, None),
        "non_compliance_fine_cents": ("integer", True, None),
        "performance_standards": ("list", True, None),
        "data_completeness_min_pct": ("number", False, None),
        "correction_tolerance_pct": ("number", False, None),
        "anomaly_yoy_threshold_pct": ("number", False, None),
        "weather_adjustment_factor": ("number", False, None),
    }, allow_empty=False)
    _validate_covered_property_types(body["covered_property_types"])
    _validate_performance_standards(body["performance_standards"])
    for c in store.cycles.values():
        if c["cycle_year"] == body["cycle_year"]:
            raise ApiError("ERR_INVALID_REQUEST", 400, "cycle_year must be unique")
    cycle = db.new_common({
        "id": db.new_id(),
        "cycle_year": body["cycle_year"],
        "filing_deadline_at": parse_datetime(body["filing_deadline_at"]),
        "covered_floor_area_threshold_sqft": body["covered_floor_area_threshold_sqft"],
        "covered_property_types": list(body["covered_property_types"]),
        "late_fine_daily_rate_cents": body["late_fine_daily_rate_cents"],
        "late_fine_cap_days": body["late_fine_cap_days"],
        "non_compliance_fine_cents": body["non_compliance_fine_cents"],
        "data_completeness_min_pct": body.get("data_completeness_min_pct", 90),
        "correction_tolerance_pct": body.get("correction_tolerance_pct", 5),
        "anomaly_yoy_threshold_pct": body.get("anomaly_yoy_threshold_pct", 25),
        "weather_adjustment_factor": body.get("weather_adjustment_factor", 1.0),
        "performance_standards": body["performance_standards"],
        "status": "SCHEDULED",
        "created_by_officer_id": uid,
        "published_at": None,
    })
    store.cycles[cycle["id"]] = cycle
    return created(cycle)


@bp.get("/v1/reporting-cycles/<cycle_id>")
def get_cycle(cycle_id):
    get_context()
    cycle = require_path_entity(store.cycles, cycle_id)
    return ok(cycle)


_EDITABLE_FIELDS = {
    "filing_deadline_at": ("datetime", False, None),
    "late_fine_daily_rate_cents": ("integer", False, None),
    "late_fine_cap_days": ("integer", False, None),
    "non_compliance_fine_cents": ("integer", False, None),
    "weather_adjustment_factor": ("number", False, None),
    "performance_standards": ("list", False, None),
    "data_completeness_min_pct": ("number", False, None),
    "correction_tolerance_pct": ("number", False, None),
    "anomaly_yoy_threshold_pct": ("number", False, None),
}


@bp.patch("/v1/reporting-cycles/<cycle_id>")
def patch_cycle(cycle_id):
    get_context()
    require_roles(["ComplianceOfficer"])
    cycle = require_path_entity(store.cycles, cycle_id)
    body = json_object()
    # OCC (tier 5): presence/type, then version match, before other input semantics.
    expected = body.get("expected_cycle_version")
    if not is_integer(expected):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "expected_cycle_version is required and must be an integer")
    if expected != cycle["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_cycle_version does not match the current version")
    schema = dict(_EDITABLE_FIELDS)
    schema["expected_cycle_version"] = ("integer", True, None)
    from validation import validate_schema
    validate_schema(body, schema)
    if cycle["status"] not in ("SCHEDULED", "OPEN"):
        raise ApiError("ERR_CYCLE_NOT_EDITABLE", 409,
                       "Cycle configuration may only be edited while SCHEDULED or OPEN")
    if "performance_standards" in body:
        _validate_performance_standards(body["performance_standards"])
    for field in _EDITABLE_FIELDS:
        if field not in body:
            continue
        if field == "filing_deadline_at":
            cycle[field] = parse_datetime(body[field])
        else:
            cycle[field] = body[field]
    db.touch(cycle)
    return ok(cycle)


@bp.post("/v1/reporting-cycles/<cycle_id>/open")
def open_cycle(cycle_id):
    get_context()
    require_roles(["ComplianceOfficer"])
    cycle = require_path_entity(store.cycles, cycle_id)
    if cycle["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a SCHEDULED cycle can be opened")
    cycle["status"] = "OPEN"
    db.touch(cycle)
    return ok(cycle)


@bp.post("/v1/reporting-cycles/<cycle_id>/close-filing")
def close_filing(cycle_id):
    get_context()
    require_roles(["ComplianceOfficer"])
    cycle = require_path_entity(store.cycles, cycle_id)
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only an OPEN cycle can be closed for filing")
    if not (db.LOGICAL_CLOCK > cycle["filing_deadline_at"]):
        raise ApiError("ERR_CYCLE_NOT_CLOSABLE", 409,
                       "close-filing requires the current time to be strictly past "
                       "filing_deadline_at")
    cycle["status"] = "FILING_CLOSED"
    db.touch(cycle)
    core.close_filing_sweep(cycle)
    return ok(cycle)
