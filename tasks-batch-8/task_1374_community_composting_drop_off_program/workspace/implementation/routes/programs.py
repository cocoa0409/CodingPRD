"""Program endpoints."""

from flask import Blueprint

import db
import errors
from middleware import require_roles, ALL_ROLES
from response import success_object
from routes.helpers import (
    body, require_fields, require_str, require_int, get_program_or_404,
)
from services import posture as posture_svc
from services.programs import serialize_program, touch, run_ops

bp = Blueprint("programs", __name__)


@bp.route("/programs", methods=["POST"])
def create_program():
    require_roles("ProgramAdmin")
    data = body()
    require_fields(data, "name", "fiscal_year")
    name = require_str(data, "name")
    fy = require_int(data, "fiscal_year")

    pct = data.get("posture_contam_threshold", 3)
    pcmp = data.get("posture_complaint_threshold", 2)
    dcr = data.get("diversion_credit_rate", 1.0)
    if isinstance(pct, bool) or not isinstance(pct, int):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "posture_contam_threshold must be an integer")
    if isinstance(pcmp, bool) or not isinstance(pcmp, int):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "posture_complaint_threshold must be an integer")
    if isinstance(dcr, bool) or not isinstance(dcr, (int, float)):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "diversion_credit_rate must be a number")

    now = db.iso_now()
    program = {
        "id": db.new_id(),
        "name": name,
        "fiscal_year": fy,
        "status": "DRAFT",
        "posture_contam_threshold": pct,
        "posture_complaint_threshold": pcmp,
        "diversion_credit_rate": dcr,
        "ops_run_index": 0,
        "total_diverted_kg": 0.0,
        "total_contamination_kg": 0.0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.programs[program["id"]] = program
    return success_object(serialize_program(program), status=201)


@bp.route("/programs/<program_id>", methods=["GET"])
def get_program(program_id):
    require_roles(*ALL_ROLES)
    program = get_program_or_404(program_id)
    return success_object(serialize_program(program))


@bp.route("/programs/<program_id>/activate", methods=["POST"])
def activate_program(program_id):
    require_roles("ProgramAdmin")
    program = get_program_or_404(program_id)

    if program["status"] == "DRAFT":
        # Preconditions only checked on DRAFT -> ACTIVE
        has_operational = any(
            s["program_id"] == program["id"] and s["status"] == "OPERATIONAL"
            for s in db.sites.values()
        )
        if not has_operational:
            errors.raise_err(
                errors.ERR_PROGRAM_NO_OPERATIONAL_SITE,
                "Program activation requires at least one OPERATIONAL site",
            )
        has_material = any(
            m["program_id"] == program["id"] and m["active"]
            for m in db.materials.values()
        )
        if not has_material:
            errors.raise_err(
                errors.ERR_PROGRAM_NO_MATERIAL_CATEGORY,
                "Program activation requires at least one active MaterialCategory",
            )
        program["status"] = "ACTIVE"
        # Posture hard override references program.status — recompute now that
        # the program is ACTIVE (a freshly commissioned site lands at OPEN).
        for s in db.sites.values():
            if s["program_id"] == program["id"]:
                posture_svc.recompute_site_posture(s)
    elif program["status"] == "SUSPENDED":
        program["status"] = "ACTIVE"
        # Side effect: recompute all site postures from scratch
        for s in db.sites.values():
            if s["program_id"] == program["id"]:
                posture_svc.recompute_site_posture(s)
    else:
        errors.raise_err(errors.ERR_INVALID_STATE, "Program cannot be activated from current state")

    touch(program)
    return success_object(serialize_program(program))


@bp.route("/programs/<program_id>/suspend", methods=["POST"])
def suspend_program(program_id):
    require_roles("ProgramAdmin")
    program = get_program_or_404(program_id)
    if program["status"] != "ACTIVE":
        errors.raise_err(errors.ERR_INVALID_STATE, "Program must be ACTIVE to suspend")
    program["status"] = "SUSPENDED"
    # Force all site postures to SUSPENDED
    for s in db.sites.values():
        if s["program_id"] == program["id"]:
            s["posture"] = "SUSPENDED"
    touch(program)
    return success_object(serialize_program(program))


@bp.route("/programs/<program_id>/close", methods=["POST"])
def close_program(program_id):
    require_roles("ProgramAdmin")
    program = get_program_or_404(program_id)
    if program["status"] != "ACTIVE":
        errors.raise_err(errors.ERR_INVALID_STATE, "Program must be ACTIVE to close")
    has_operational = any(
        s["program_id"] == program["id"] and s["status"] == "OPERATIONAL"
        for s in db.sites.values()
    )
    if has_operational:
        errors.raise_err(
            errors.ERR_PROGRAM_HAS_OPERATIONAL_SITES,
            "Program close blocked while OPERATIONAL sites remain",
        )
    program["status"] = "CLOSED"
    touch(program)
    return success_object(serialize_program(program))


@bp.route("/programs/<program_id>/run_ops", methods=["POST"])
def run_ops_endpoint(program_id):
    require_roles("ProgramAdmin")
    program = get_program_or_404(program_id)
    run_ops(program)
    return success_object(serialize_program(program))
