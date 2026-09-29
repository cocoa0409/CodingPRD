"""Charger catalogue and motive-power fleet sizing quotes."""
from flask import Blueprint, g

from authz import (
    FLEET_ENGINEER,
    PLANT_ADMIN,
    PRODUCTION_SUPERVISOR,
    WARRANTY_ADMINISTRATOR,
    endpoint,
)
from errors import ApiError
from helpers import apply_filters, lookup, paginated, unique_or_conflict
from response import object_response
from store import db
from services.constants import CHEMISTRIES
from services.sizing import size_fleet

bp = Blueprint("chargers", __name__)

CHARGER_READERS = [PLANT_ADMIN, FLEET_ENGINEER, WARRANTY_ADMINISTRATOR]
REQUEST_READERS = [PLANT_ADMIN, FLEET_ENGINEER, PRODUCTION_SUPERVISOR]

CHARGER_SPEC = {
    "model_code": {"type": "string", "required": True},
    "chemistry_compatibility": {"type": "enum", "required": True, "values": CHEMISTRIES},
    "output_voltage_v": {"type": "number", "required": True, "gt": 0},
    "output_amps": {"type": "number", "required": True, "gt": 0},
    "charge_profile": {
        "type": "enum",
        "required": True,
        "values": ["FERRO", "HF_MODULAR", "LITHIUM_CCCV"],
    },
    "price_cents": {"type": "int", "required": True, "gt": 0},
}

CHARGER_PATCH_SPEC = {
    "charger_status": {"type": "enum", "values": ["AVAILABLE", "DISCONTINUED"]},
    "price_cents": {"type": "int", "gt": 0},
}

SIZING_SPEC = {
    "plant_id": {"type": "id", "required": True},
    "application_name": {"type": "string", "required": True},
    "forklift_class": {
        "type": "enum",
        "required": True,
        "values": ["CLASS_I", "CLASS_II", "CLASS_III"],
    },
    "forklift_count": {"type": "int", "required": True, "gte": 1, "lte": 200},
    "shift_energy_kwh_per_shift": {"type": "number", "required": True, "gt": 0},
    "shifts_per_day": {"type": "int", "required": True, "gte": 1, "lte": 3},
    "ambient_temp_c": {"type": "number", "required": True, "gte": -30, "lte": 50},
    "required_voltage_v": {"type": "number", "required": True, "gt": 0},
    "compartment_max_kg": {"type": "number", "required": True, "gt": 0},
    "charge_window_hours": {"type": "number", "required": True, "gt": 0, "lte": 24},
    "chemistry_preference": {
        "type": "enum",
        "values": CHEMISTRIES + ["ANY"],
        "default": "ANY",
    },
}

DECISION_SPEC = {
    "action": {"type": "enum", "required": True, "values": ["ACCEPT", "WITHDRAW"]},
    "decision_note": {"type": "string", "allow_blank": True},
}

CHARGER_FILTERS = {"charge_profile": "charge_profile", "charger_status": "charger_status"}
REQUEST_FILTERS = {
    "plant_id": "plant_id",
    "selected_cell_design_id": "selected_cell_design_id",
    "selected_charger_id": "selected_charger_id",
    "request_state": "request_state",
}
DEFAULT_ORDER = [("created_at", "asc"), ("id", "asc")]


@bp.post("/chargers")
@endpoint([FLEET_ENGINEER], body=CHARGER_SPEC)
def create_charger():
    payload = g.body
    unique_or_conflict("chargers", "model_code", payload["model_code"])
    record = {
        "model_code": payload["model_code"],
        "chemistry_compatibility": payload["chemistry_compatibility"],
        "output_voltage_v": payload["output_voltage_v"],
        "output_amps": payload["output_amps"],
        "charge_profile": payload["charge_profile"],
        "price_cents": payload["price_cents"],
        "charger_status": "AVAILABLE",
    }
    db.insert("chargers", record)
    return object_response(record, 201)


@bp.get("/chargers")
@endpoint(CHARGER_READERS, paginated=True)
def list_chargers():
    return paginated(apply_filters(db.rows("chargers"), CHARGER_FILTERS), DEFAULT_ORDER)


@bp.get("/chargers/<charger_id>")
@endpoint(CHARGER_READERS)
def read_charger(charger_id):
    return object_response(lookup("chargers", charger_id, "ERR_CHARGER_NOT_FOUND"))


@bp.patch("/chargers/<charger_id>")
@endpoint([FLEET_ENGINEER], body=CHARGER_PATCH_SPEC, at_least_one=True)
def update_charger(charger_id):
    charger = lookup("chargers", charger_id, "ERR_CHARGER_NOT_FOUND")
    payload = g.body
    for field in ("charger_status", "price_cents"):
        if field in payload:
            charger[field] = payload[field]
    db.touch(charger)
    return object_response(charger)


@bp.post("/fleet-sizing-requests")
@endpoint([FLEET_ENGINEER], body=SIZING_SPEC)
def create_sizing_request():
    payload = g.body
    plant = lookup("plants", payload["plant_id"])
    # Raises ERR_NO_ELIGIBLE_CELL_DESIGN / ERR_NO_CHARGER_MATCH; nothing persists.
    outcome = size_fleet(payload)
    record = {
        "plant_id": plant["id"],
        "application_name": payload["application_name"],
        "forklift_class": payload["forklift_class"],
        "forklift_count": payload["forklift_count"],
        "shift_energy_kwh_per_shift": payload["shift_energy_kwh_per_shift"],
        "shifts_per_day": payload["shifts_per_day"],
        "ambient_temp_c": payload["ambient_temp_c"],
        "required_voltage_v": payload["required_voltage_v"],
        "compartment_max_kg": payload["compartment_max_kg"],
        "charge_window_hours": payload["charge_window_hours"],
        "chemistry_preference": payload.get("chemistry_preference") or "ANY",
        "request_state": "MATCHED",
    }
    record.update(outcome)
    db.insert("fleet_sizing_requests", record)
    return object_response(record, 201)


@bp.get("/fleet-sizing-requests")
@endpoint(REQUEST_READERS, paginated=True)
def list_sizing_requests():
    rows = apply_filters(db.rows("fleet_sizing_requests"), REQUEST_FILTERS)
    return paginated(rows, DEFAULT_ORDER)


@bp.get("/fleet-sizing-requests/<request_id>")
@endpoint(REQUEST_READERS)
def read_sizing_request(request_id):
    return object_response(
        lookup("fleet_sizing_requests", request_id, "ERR_SIZING_REQUEST_NOT_FOUND")
    )


@bp.post("/fleet-sizing-requests/<request_id>/decision")
@endpoint([FLEET_ENGINEER], body=DECISION_SPEC)
def decide_sizing_request(request_id):
    row = lookup("fleet_sizing_requests", request_id, "ERR_SIZING_REQUEST_NOT_FOUND")
    if row["request_state"] != "MATCHED":
        raise ApiError(
            "ERR_SIZING_REQUEST_STATE_INVALID", "Only a MATCHED request may be decided"
        )
    row["request_state"] = "ACCEPTED" if g.body["action"] == "ACCEPT" else "WITHDRAWN"
    db.touch(row)
    return object_response(row)
