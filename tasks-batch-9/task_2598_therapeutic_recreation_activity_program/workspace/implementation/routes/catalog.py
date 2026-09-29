"""Program, room and vehicle catalogue endpoints (PRD 3.4 / 3.8)."""
from flask import Blueprint

import serializers
from db import store
from helpers import ctx, load, new_entity
from middleware import (
    ROLE_ACTIVITY_AIDE,
    ROLE_ACTIVITY_DIRECTOR,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_COUNCIL_REPRESENTATIVE,
    ROLE_RECREATION_THERAPIST,
    ROLE_VOLUNTEER_COORDINATOR,
    authorize,
)
from response import object_response
from services import constants as C
from validation import read_body, validate

bp = Blueprint("catalog", __name__)

PROGRAM_SPEC = {
    "name": {"type": "string", "max_len": 120, "required": True},
    "domain": {"type": "enum", "values": C.DOMAINS, "required": True},
    "staffing_ratio_denominator": {
        "type": "int",
        "min": 1,
        "max": 20,
        "required": True,
    },
    "max_group_size": {"type": "int", "min": 1, "max": 60, "required": True},
    "max_supervision_tier": {"type": "enum", "values": C.TIERS, "required": True},
    "required_adaptive_equipment": {"type": "enum_array", "values": C.EQUIPMENT},
    "volunteer_eligible": {"type": "bool"},
    "required_screening_level": {"type": "enum", "values": C.SCREENING_LEVELS},
}

ROOM_SPEC = {
    "name": {"type": "string", "max_len": 80, "required": True},
    "capacity": {"type": "int", "min": 1, "max": 200, "required": True},
    "buffer_minutes": {"type": "int", "min": 0, "max": 120},
    "equipment_available": {"type": "enum_array", "values": C.EQUIPMENT},
}

VEHICLE_SPEC = {
    "label": {"type": "string", "max_len": 60, "required": True},
    "ambulatory_seats": {"type": "int", "min": 0, "max": 40, "required": True},
    "wheelchair_stations": {"type": "int", "min": 0, "max": 8, "required": True},
    "turnaround_minutes": {"type": "int", "min": 0, "max": 240},
    "status": {"type": "enum", "values": C.VEHICLE_STATUSES},
}

VEHICLE_PATCH_SPEC = {
    "label": {"type": "string", "max_len": 60},
    "status": {"type": "enum", "values": C.VEHICLE_STATUSES},
    "turnaround_minutes": {"type": "int", "min": 0, "max": 240},
}


@bp.post("/programs")
def create_program():
    authorize(ROLE_ACTIVITY_DIRECTOR)
    values = validate(read_body(), PROGRAM_SPEC)
    program = new_entity(
        {
            "name": values["name"],
            "domain": values["domain"],
            "staffing_ratio_denominator": values["staffing_ratio_denominator"],
            "max_group_size": values["max_group_size"],
            "max_supervision_tier": values["max_supervision_tier"],
            "required_adaptive_equipment": values["required_adaptive_equipment"] or [],
            "volunteer_eligible": (
                values["volunteer_eligible"]
                if values["volunteer_eligible"] is not None
                else False
            ),
            "required_screening_level": values["required_screening_level"] or "NONE",
            "council_preference_weight": 0,
        }
    )
    store.programs[program["id"]] = program
    return object_response(serializers.program(program), 201)


@bp.get("/programs/<program_id>")
def get_program(program_id):
    authorize(
        ROLE_ACTIVITY_DIRECTOR,
        ROLE_RECREATION_THERAPIST,
        ROLE_ACTIVITY_AIDE,
        ROLE_VOLUNTEER_COORDINATOR,
        ROLE_COMPLIANCE_OFFICER,
        ROLE_COUNCIL_REPRESENTATIVE,
    )
    program = load("program", program_id)
    return object_response(serializers.program(program), 200)


@bp.post("/rooms")
def create_room():
    authorize(ROLE_ACTIVITY_DIRECTOR)
    values = validate(read_body(), ROOM_SPEC)
    room = new_entity(
        {
            "name": values["name"],
            "capacity": values["capacity"],
            "buffer_minutes": (
                values["buffer_minutes"]
                if values["buffer_minutes"] is not None
                else 0
            ),
            "equipment_available": values["equipment_available"] or [],
        }
    )
    store.rooms[room["id"]] = room
    return object_response(serializers.room(room), 201)


@bp.post("/vehicles")
def create_vehicle():
    authorize(ROLE_ACTIVITY_DIRECTOR)
    values = validate(read_body(), VEHICLE_SPEC)
    vehicle = new_entity(
        {
            "label": values["label"],
            "ambulatory_seats": values["ambulatory_seats"],
            "wheelchair_stations": values["wheelchair_stations"],
            "turnaround_minutes": (
                values["turnaround_minutes"]
                if values["turnaround_minutes"] is not None
                else 30
            ),
            "status": values["status"] or "AVAILABLE",
            "reserved_ambulatory_seats": 0,
            "reserved_wheelchair_stations": 0,
        }
    )
    store.vehicles[vehicle["id"]] = vehicle
    return object_response(serializers.vehicle(vehicle), 201)


@bp.patch("/vehicles/<vehicle_id>")
def patch_vehicle(vehicle_id):
    authorize(ROLE_ACTIVITY_DIRECTOR)
    vehicle = load("vehicle", vehicle_id)
    values = validate(read_body(), VEHICLE_PATCH_SPEC)
    context = ctx()
    for field in ("label", "status", "turnaround_minutes"):
        if values[field] is not None:
            vehicle[field] = values[field]
    context.bump(vehicle)
    return object_response(serializers.vehicle(vehicle), 200)


@bp.get("/vehicles/<vehicle_id>")
def get_vehicle(vehicle_id):
    authorize(ROLE_ACTIVITY_DIRECTOR, ROLE_ACTIVITY_AIDE, ROLE_COMPLIANCE_OFFICER)
    vehicle = load("vehicle", vehicle_id)
    return object_response(serializers.vehicle(vehicle), 200)
