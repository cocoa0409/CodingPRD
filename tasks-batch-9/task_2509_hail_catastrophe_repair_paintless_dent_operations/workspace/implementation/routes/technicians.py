"""Technician endpoints (PRD §3.3)."""

from flask import Blueprint

import serializers
from db import base_row, db
from middleware import authenticate
from response import object_response
from routes.common import get_technician
from services.constants import SKILL_TIERS
from validation import json_body, req_date_string, req_enum, req_number, req_state_code, req_string

bp = Blueprint("technicians", __name__)

READ_ROLES = (
    "CatastropheDirector",
    "CrewCoordinator",
    "ShopEstimator",
    "IntakeAdvisor",
    "PdrTechnician",
    "QualityInspector",
)


@bp.post("/hail-ops/technicians")
def create_technician():
    authenticate(("CrewCoordinator",))
    body = json_body()
    full_name = req_string(body, "full_name")
    home_state_code = req_string(body, "home_state_code")
    license_state_code = req_state_code(body, "license_state_code")
    license_expires_at = req_date_string(body, "license_expires_at")
    skill_tier = req_enum(body, "skill_tier", SKILL_TIERS)
    flat_split_pct = req_number(body, "flat_split_pct", exclusive_minimum=0, maximum=1)

    row = base_row()
    row.update({
        "full_name": full_name,
        "home_state_code": home_state_code,
        "license_state_code": license_state_code,
        "license_expires_at": license_expires_at,
        "skill_tier": skill_tier,
        "flat_split_pct": flat_split_pct,
    })
    db.technicians[row["id"]] = row
    return object_response(serializers.technician(row), 201)


@bp.get("/hail-ops/technicians/<identifier>")
def read_technician(identifier):
    authenticate(READ_ROLES)
    technician = get_technician(identifier)
    return object_response(serializers.technician(technician))
