"""Property endpoints (PRD §3.1, §3.9)."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import authenticate, require_roles
from response import created, ok
from validation import get_body, validate_schema

bp = Blueprint("properties", __name__)

PROPERTY_SCHEMA = {
    "name": ("string", True, None),
    "days_to_ready_target": ("integer", True, None),
    "pm_threshold_bp": ("integer", True, None),
    "rm_threshold_bp": ("integer", True, None),
    "capital_threshold_cents": ("integer", True, None),
    "replacement_policy": ("enum", True, ["PERCENT_OF_REPLACE", "COST_PER_YEAR"]),
}


@bp.post("/make-ready/properties")
def create_property():
    authenticate()
    require_roles(["RegionalManager"])
    body = get_body()
    validate_schema(body, PROPERTY_SCHEMA)
    if body["rm_threshold_bp"] < body["pm_threshold_bp"]:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "rm_threshold_bp must be >= pm_threshold_bp")
    prop = {
        "id": db.new_id(),
        "name": body["name"],
        "days_to_ready_target": body["days_to_ready_target"],
        "pm_threshold_bp": body["pm_threshold_bp"],
        "rm_threshold_bp": body["rm_threshold_bp"],
        "capital_threshold_cents": body["capital_threshold_cents"],
        "replacement_policy": body["replacement_policy"],
        "benchmark_turn_count": 0,
        "avg_booked_expense_cents": 0,
        "avg_days_to_ready": 0,
    }
    db.new_common(prop)
    store.properties[prop["id"]] = prop
    return created(prop)


@bp.get("/make-ready/properties/<property_id>/turn-benchmark")
def get_turn_benchmark(property_id):
    authenticate()
    require_roles(["RegionalManager", "PropertyManager"])
    prop = store.properties.get(property_id)
    if prop is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Property not found")
    return ok({
        "benchmark_turn_count": prop["benchmark_turn_count"],
        "avg_booked_expense_cents": prop["avg_booked_expense_cents"],
        "avg_days_to_ready": prop["avg_days_to_ready"],
    })
