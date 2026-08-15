"""TransmissionModel endpoints."""

import uuid

from flask import Blueprint, request

from db import db
from errors import ApiError, ERR_MODEL_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import require_role
from response import success
from services.serializers import model_view
from validators import (
    get_json_body, require_fields, check_string, check_int, check_number,
    check_positive, invalid, parse_limit_offset, paginate,
)

bp = Blueprint("models", __name__)


def _validate_dyno_targets(value):
    if not isinstance(value, list):
        invalid("Field dyno_targets must be an array")
    for entry in value:
        if not isinstance(entry, dict):
            invalid("dyno_targets entries must be objects")
        if "gear" not in entry or "target_pressure_kpa" not in entry:
            invalid("dyno_targets entries require gear and target_pressure_kpa")
        check_int(entry["gear"], "dyno_targets.gear")
        check_number(entry["target_pressure_kpa"], "dyno_targets.target_pressure_kpa")


def _validate_required_parts(value):
    if not isinstance(value, list):
        invalid("Field required_parts must be an array")
    for entry in value:
        if not isinstance(entry, dict):
            invalid("required_parts entries must be objects")
        if "part_family" not in entry or "qty" not in entry:
            invalid("required_parts entries require part_family and qty")
        check_string(entry["part_family"], "required_parts.part_family")
        check_int(entry["qty"], "required_parts.qty")
        check_positive(entry["qty"], "required_parts.qty")


@bp.post("/api/transmission-models")
def create_model():
    require_role({"ProgramAdmin"})
    body = get_json_body()
    require_fields(
        body,
        [
            "model_code", "year_start", "year_end", "make", "model",
            "core_deposit_cents", "flat_rate_hours", "labor_cap_cents",
            "dyno_targets", "required_parts",
        ],
    )
    check_string(body["model_code"], "model_code")
    check_int(body["year_start"], "year_start")
    check_int(body["year_end"], "year_end")
    check_string(body["make"], "make")
    check_string(body["model"], "model")
    check_int(body["core_deposit_cents"], "core_deposit_cents")
    check_positive(body["core_deposit_cents"], "core_deposit_cents")
    check_number(body["flat_rate_hours"], "flat_rate_hours")
    check_positive(body["flat_rate_hours"], "flat_rate_hours")
    check_int(body["labor_cap_cents"], "labor_cap_cents")
    check_positive(body["labor_cap_cents"], "labor_cap_cents")
    if body["year_end"] < body["year_start"]:
        invalid("year_end must be >= year_start")
    warranty_days = body.get("warranty_days", 365)
    check_int(warranty_days, "warranty_days")
    check_positive(warranty_days, "warranty_days")
    _validate_dyno_targets(body["dyno_targets"])
    _validate_required_parts(body["required_parts"])

    if any(m["model_code"] == body["model_code"] for m in db.transmission_models.values()):
        invalid("model_code must be unique")

    now = db.now()
    m = {
        "id": str(uuid.uuid4()),
        "model_code": body["model_code"],
        "year_start": body["year_start"],
        "year_end": body["year_end"],
        "make": body["make"],
        "model": body["model"],
        "core_deposit_cents": body["core_deposit_cents"],
        "flat_rate_hours": body["flat_rate_hours"],
        "labor_cap_cents": body["labor_cap_cents"],
        "warranty_days": warranty_days,
        "dyno_targets": body["dyno_targets"],
        "required_parts": body["required_parts"],
        "spec_version": 1,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.transmission_models[m["id"]] = m
    return success(model_view(m), "object", 201)


@bp.put("/api/transmission-models/<mid>")
def update_model(mid):
    require_role({"ProgramAdmin"})
    body = get_json_body()
    m = db.transmission_models.get(mid)
    if m is None:
        raise ApiError(ERR_MODEL_NOT_FOUND, "TransmissionModel id does not exist", 404)

    updates = {}
    if "core_deposit_cents" in body:
        check_int(body["core_deposit_cents"], "core_deposit_cents")
        check_positive(body["core_deposit_cents"], "core_deposit_cents")
        updates["core_deposit_cents"] = body["core_deposit_cents"]
    if "flat_rate_hours" in body:
        check_number(body["flat_rate_hours"], "flat_rate_hours")
        check_positive(body["flat_rate_hours"], "flat_rate_hours")
        updates["flat_rate_hours"] = body["flat_rate_hours"]
    if "labor_cap_cents" in body:
        check_int(body["labor_cap_cents"], "labor_cap_cents")
        check_positive(body["labor_cap_cents"], "labor_cap_cents")
        updates["labor_cap_cents"] = body["labor_cap_cents"]
    if "warranty_days" in body:
        check_int(body["warranty_days"], "warranty_days")
        check_positive(body["warranty_days"], "warranty_days")
        updates["warranty_days"] = body["warranty_days"]
    if "dyno_targets" in body:
        _validate_dyno_targets(body["dyno_targets"])
        updates["dyno_targets"] = body["dyno_targets"]
    if "required_parts" in body:
        _validate_required_parts(body["required_parts"])
        updates["required_parts"] = body["required_parts"]

    m.update(updates)
    m["spec_version"] += 1
    m["version"] += 1
    m["updated_at"] = db.now()
    return success(model_view(m), "object", 200)


@bp.get("/api/transmission-models/<mid>")
def get_model(mid):
    require_role({"Any"})
    m = db.transmission_models.get(mid)
    if m is None:
        raise ApiError(ERR_MODEL_NOT_FOUND, "TransmissionModel id does not exist", 404)
    return success(model_view(m), "object", 200)
