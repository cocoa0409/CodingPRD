"""Program endpoints."""

from __future__ import annotations

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object
from routes.common import get_body, paginate, fetch_or_404

bp = Blueprint("programs", __name__)


@bp.post("/efficiency/programs")
def create_program():
    require_roles({"ProgramManager"})
    body = get_body()
    program = {
        "code": body.get("code"),
        "name": body.get("name"),
        "sector": body.get("sector"),
        "budget_cents": int(body.get("budget_cents") or 0),
        "committed_cents": 0,
        "paid_cents": 0,
        "avoided_kwh_target": int(body.get("avoided_kwh_target") or 0),
        "avoided_kwh_actual": 0,
        "trc_threshold": body.get("trc_threshold"),
        "status": "DRAFT",
    }
    db.stamp_new(program)
    db.programs[program["id"]] = program
    return success_object(program, 201)


@bp.get("/efficiency/programs")
def list_programs():
    require_roles({"ProgramManager", "Contractor", "Inspector", "Customer"})
    items = list(db.programs.values())
    status = request.args.get("status")
    sector = request.args.get("sector")
    if status is not None:
        items = [p for p in items if p.get("status") == status]
    if sector is not None:
        items = [p for p in items if p.get("sector") == sector]
    return paginate(items)


@bp.get("/efficiency/programs/<program_id>")
def get_program(program_id):
    require_roles({"ProgramManager", "Contractor", "Inspector", "Customer"})
    return success_object(fetch_or_404(db.programs, program_id, "Program"))


@bp.post("/efficiency/programs/<program_id>/activate")
def activate_program(program_id):
    require_roles({"ProgramManager"})
    program = fetch_or_404(db.programs, program_id, "Program")
    if program["status"] not in ("DRAFT", "SUSPENDED"):
        raise errors.invalid_state(f"Program in {program['status']} cannot be activated")
    if program["status"] == "DRAFT":
        if not (program.get("budget_cents") or 0) > 0:
            raise errors.invalid_state("budget_cents must be positive to activate")
        if program.get("trc_threshold") is None:
            raise errors.invalid_state("trc_threshold must be configured to activate")
    program["status"] = "ACTIVE"
    db.touch(program)
    return success_object(program)


@bp.post("/efficiency/programs/<program_id>/suspend")
def suspend_program(program_id):
    require_roles({"ProgramManager"})
    program = fetch_or_404(db.programs, program_id, "Program")
    if program["status"] != "ACTIVE":
        raise errors.invalid_state(f"Program in {program['status']} cannot be suspended")
    program["status"] = "SUSPENDED"
    db.touch(program)
    return success_object(program)


@bp.post("/efficiency/programs/<program_id>/close")
def close_program(program_id):
    require_roles({"ProgramManager"})
    program = fetch_or_404(db.programs, program_id, "Program")
    if program["status"] not in ("ACTIVE", "SUSPENDED"):
        raise errors.invalid_state(f"Program in {program['status']} cannot be closed")
    open_states = ("PROPOSED", "APPROVED", "SCHEDULED", "INSTALLED", "INSPECTING", "REMEDIATION")
    for p in db.projects.values():
        if p.get("program_id") == program_id and p.get("status") in open_states:
            raise errors.program_has_open_projects()
    program["status"] = "CLOSED"
    db.touch(program)
    return success_object(program)
