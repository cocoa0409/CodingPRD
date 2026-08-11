"""Contractor endpoints (PRD 3.2)."""
import db
from db import base_resource, touch
from errors import raise_err
from middleware import ALL_ROLES, require_roles
from response import ok_object
from services.core import get_or_404, list_page, ser_contractor
from flask import Blueprint, request
from validate import body, req_int, req_str

bp = Blueprint("contractors", __name__)


@bp.post("/api/contractors")
@require_roles("ProgramManager")
def create_contractor():
    b = body()
    # Body FK existence (stage 4) precedes schema (stage 5) per PRD 2.7.
    program_id = b.get("program_id")
    program = None
    if isinstance(program_id, str):
        program = get_or_404(db.programs, program_id, "Program")
    program_id = req_str(b, "program_id")
    if program is None:
        program = get_or_404(db.programs, program_id, "Program")
    name = req_str(b, "name")
    capacity = req_int(b, "crew_capacity_per_window", min=1)
    unit_price = req_int(b, "unit_price_cents", min=0)
    # Program-active gate (stage 8).
    if program["status"] != "ACTIVE":
        raise_err("ERR_PROGRAM_NOT_ACTIVE",
                  "Contractor onboarding requires an ACTIVE program")
    c = base_resource()
    c.update({
        "program_id": program["id"],
        "name": name,
        "crew_capacity_per_window": capacity,
        "unit_price_cents": unit_price,
        "quality_score_bp": 10000,
        "audits_failed_count": 0,
        "status": "ACTIVE",
    })
    db.contractors[c["id"]] = c
    return ok_object(ser_contractor(c), 201)


@bp.get("/api/contractors")
@require_roles(*ALL_ROLES)
def list_contractors():
    filters = {}
    for k in ("program_id", "status"):
        if request.args.get(k) is not None:
            filters[k] = request.args[k]
    return list_page(db.contractors.values(), filters, ser_contractor)


@bp.get("/api/contractors/<contractorId>")
@require_roles(*ALL_ROLES)
def get_contractor(contractorId):
    return ok_object(ser_contractor(get_or_404(db.contractors, contractorId, "Contractor")))


@bp.post("/api/contractors/<contractorId>/suspend")
@require_roles("ProgramManager")
def suspend_contractor(contractorId):
    c = get_or_404(db.contractors, contractorId, "Contractor")
    if c["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "Contractor is not ACTIVE")
    c["status"] = "SUSPENDED"
    touch(c)
    return ok_object(ser_contractor(c))


@bp.post("/api/contractors/<contractorId>/reinstate")
@require_roles("ProgramManager")
def reinstate_contractor(contractorId):
    c = get_or_404(db.contractors, contractorId, "Contractor")
    if c["status"] != "SUSPENDED":
        raise_err("ERR_INVALID_STATE", "Contractor is not SUSPENDED")
    c["status"] = "ACTIVE"
    touch(c)
    return ok_object(ser_contractor(c))
