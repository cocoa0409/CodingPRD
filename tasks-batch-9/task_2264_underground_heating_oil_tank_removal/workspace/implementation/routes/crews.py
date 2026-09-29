"""Crew registration and read."""

from flask import Blueprint

import calculations as calc
from db import create
from middleware import authenticate, body, opt_int, req_enum, req_str, resolve
from response import entity_response

bp = Blueprint("crews", __name__)


@bp.post("/crews")
def create_crew():
    authenticate(("ProjectCoordinator",))
    payload = body()
    crew_name = req_str(payload, "crew_name")
    cert_level = req_enum(payload, "cert_level", calc.CERT_LEVELS)
    buffer_minutes = opt_int(payload, "mobilization_buffer_minutes", 90, minimum=0)
    crew = create("crews", {
        "crew_name": crew_name,
        "cert_level": cert_level,
        "mobilization_buffer_minutes": buffer_minutes,
    })
    return entity_response(crew, 201)


@bp.get("/crews/<crew_id>")
def read_crew(crew_id):
    authenticate(("ProjectCoordinator", "FieldTechnician", "ComplianceOfficer"))
    return entity_response(resolve("crews", crew_id))
