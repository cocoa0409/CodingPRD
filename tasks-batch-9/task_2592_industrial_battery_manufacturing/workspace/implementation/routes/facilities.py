"""Formation bays and test chambers."""
from flask import Blueprint, g

from authz import (
    PLANT_ADMIN,
    PRODUCTION_SUPERVISOR,
    QUALITY_INSPECTOR,
    SAFETY_OFFICER,
    endpoint,
)
from helpers import apply_filters, lookup, paginated, unique_or_conflict
from response import object_response
from store import db

bp = Blueprint("facilities", __name__)

BAY_READERS = [PLANT_ADMIN, PRODUCTION_SUPERVISOR, QUALITY_INSPECTOR, SAFETY_OFFICER]
CHAMBER_READERS = [PLANT_ADMIN, PRODUCTION_SUPERVISOR, QUALITY_INSPECTOR]
FACILITY_STATES = ["AVAILABLE", "MAINTENANCE"]
DEFAULT_ORDER = [("created_at", "asc"), ("id", "asc")]

BAY_CREATE_SPEC = {
    "plant_id": {"type": "id", "required": True},
    "bay_code": {"type": "string", "required": True},
    "rated_power_kw": {"type": "number", "required": True, "gt": 0},
    "cooldown_minutes": {"type": "int", "gte": 0, "lte": 240, "default": 45},
}

BAY_PATCH_SPEC = {
    "bay_status": {"type": "enum", "values": FACILITY_STATES},
    "cooldown_minutes": {"type": "int", "gte": 0, "lte": 240},
}

CHAMBER_CREATE_SPEC = {
    "plant_id": {"type": "id", "required": True},
    "chamber_code": {"type": "string", "required": True},
    "power_cap_kw": {"type": "number", "required": True, "gt": 0},
}

CHAMBER_PATCH_SPEC = {
    "chamber_status": {"type": "enum", "values": FACILITY_STATES},
    "power_cap_kw": {"type": "number", "gt": 0},
}


@bp.post("/formation-bays")
@endpoint([PLANT_ADMIN], body=BAY_CREATE_SPEC)
def create_bay():
    payload = g.body
    lookup("plants", payload["plant_id"])
    unique_or_conflict(
        "formation_bays", "bay_code", payload["bay_code"], "plant_id", payload["plant_id"]
    )
    record = {
        "plant_id": payload["plant_id"],
        "bay_code": payload["bay_code"],
        "rated_power_kw": payload["rated_power_kw"],
        "cooldown_minutes": payload["cooldown_minutes"],
        "bay_status": "AVAILABLE",
    }
    db.insert("formation_bays", record)
    return object_response(record, 201)


@bp.get("/formation-bays")
@endpoint(BAY_READERS, paginated=True)
def list_bays():
    rows = apply_filters(
        db.rows("formation_bays"), {"plant_id": "plant_id", "bay_status": "bay_status"}
    )
    return paginated(rows, DEFAULT_ORDER)


@bp.get("/formation-bays/<bay_id>")
@endpoint(BAY_READERS)
def read_bay(bay_id):
    return object_response(lookup("formation_bays", bay_id))


@bp.patch("/formation-bays/<bay_id>")
@endpoint([PLANT_ADMIN], body=BAY_PATCH_SPEC, at_least_one=True)
def patch_bay(bay_id):
    bay = lookup("formation_bays", bay_id)
    for field in BAY_PATCH_SPEC:
        if field in g.body:
            bay[field] = g.body[field]
    db.touch(bay)
    return object_response(bay)


@bp.post("/test-chambers")
@endpoint([PLANT_ADMIN], body=CHAMBER_CREATE_SPEC)
def create_chamber():
    payload = g.body
    lookup("plants", payload["plant_id"])
    unique_or_conflict(
        "test_chambers",
        "chamber_code",
        payload["chamber_code"],
        "plant_id",
        payload["plant_id"],
    )
    record = {
        "plant_id": payload["plant_id"],
        "chamber_code": payload["chamber_code"],
        "power_cap_kw": payload["power_cap_kw"],
        "chamber_status": "AVAILABLE",
    }
    db.insert("test_chambers", record)
    return object_response(record, 201)


@bp.get("/test-chambers")
@endpoint(CHAMBER_READERS, paginated=True)
def list_chambers():
    rows = apply_filters(
        db.rows("test_chambers"),
        {"plant_id": "plant_id", "chamber_status": "chamber_status"},
    )
    return paginated(rows, DEFAULT_ORDER)


@bp.get("/test-chambers/<chamber_id>")
@endpoint(CHAMBER_READERS)
def read_chamber(chamber_id):
    return object_response(lookup("test_chambers", chamber_id))


@bp.patch("/test-chambers/<chamber_id>")
@endpoint([PLANT_ADMIN], body=CHAMBER_PATCH_SPEC, at_least_one=True)
def patch_chamber(chamber_id):
    chamber = lookup("test_chambers", chamber_id)
    for field in CHAMBER_PATCH_SPEC:
        if field in g.body:
            chamber[field] = g.body[field]
    db.touch(chamber)
    return object_response(chamber)
