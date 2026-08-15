"""GrantProgram and GrantApplication endpoints (PRD 3.8)."""

from flask import Blueprint

import db
from errors import (
    ApiError, ERR_APPLICATION_STATE_FORBIDS, ERR_APPLICATION_WINDOW_CLOSED,
    ERR_DUPLICATE_APPLICATION, ERR_GRANT_APPLICATION_NOT_FOUND,
    ERR_GRANT_POOL_EXHAUSTED, ERR_GRANT_PROGRAM_NOT_FOUND,
    ERR_INCOME_ABOVE_CAP, ERR_PROGRAM_NOT_OPEN, ERR_PROGRAM_STATE_FORBIDS,
    ERR_PROJECT_NOT_FOUND, ERR_PROJECT_STATE_FORBIDS,
    ERR_PROJECT_TYPE_INELIGIBLE, ERR_VERIFIED_INCOME_INELIGIBLE,
    state_forbids,
)
from middleware import (
    DEALER_ADMIN, GRANT_OFFICER, HOMEOWNER, ALL_ROLES, require_roles,
)
from response import ok
from routes.common import get_or_404, list_endpoint, require_property_ownership
from services import calc, cascade
from util import dec, get_json_body, serialize, validate_body

bp = Blueprint("grants", __name__)

PROJECT_TYPES = ["NEW_INSTALLATION", "MODERNIZATION"]

PROGRAM_SPEC = {
    "program_name": ("string", True, None),
    "funder_name": ("string", True, None),
    "max_award": ("money", True, None),
    "income_cap": ("money", True, None),
    "coverage_percent": ("number", True, None),
    "total_pool": ("money", True, None),
    "application_open_date": ("datetime", True, None),
    "application_close_date": ("datetime", True, None),
    "eligible_project_types": ("enum_array", True, PROJECT_TYPES),
}

APPLICATION_SPEC = {
    "project_id": ("string", True, None),
    "program_id": ("string", True, None),
    "household_income": ("money", True, None),
}

SUBMITTABLE_PROJECT_STATES = (
    "QUOTED", "PERMIT_IN_PROGRESS", "PERMIT_APPROVED",
    "STRUCTURAL_IN_PROGRESS", "READY_FOR_INSTALL", "INSTALL_SCHEDULED",
)


# --- GrantProgram -----------------------------------------------------------

@bp.post("/api/grant-programs")
@require_roles(DEALER_ADMIN)
def create_program():
    vals = validate_body(get_json_body(), PROGRAM_SPEC)
    rec = db.new_record({
        "program_name": vals["program_name"],
        "funder_name": vals["funder_name"],
        "max_award": vals["max_award"],
        "income_cap": vals["income_cap"],
        "coverage_percent": vals["coverage_percent"],
        "total_pool": vals["total_pool"],
        "remaining_pool": vals["total_pool"],
        "application_open_date": vals["application_open_date"],
        "application_close_date": vals["application_close_date"],
        "eligible_project_types": vals["eligible_project_types"],
        "status": "OPEN",
    })
    db.grant_programs[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.get("/api/grant-programs")
@require_roles(*ALL_ROLES)
def list_programs():
    return list_endpoint(db.grant_programs, {"status": "status"})


@bp.get("/api/grant-programs/<programId>")
@require_roles(*ALL_ROLES)
def get_program(programId):
    rec = get_or_404(db.grant_programs, programId, ERR_GRANT_PROGRAM_NOT_FOUND, "GrantProgram")
    return ok(serialize(rec))


@bp.post("/api/grant-programs/<programId>/pause")
@require_roles(DEALER_ADMIN)
def pause_program(programId):
    rec = get_or_404(db.grant_programs, programId, ERR_GRANT_PROGRAM_NOT_FOUND, "GrantProgram")
    if rec["status"] != "OPEN":
        raise state_forbids(ERR_PROGRAM_STATE_FORBIDS, "GrantProgram")
    rec["status"] = "PAUSED"
    db.touch(rec)
    return ok(serialize(rec))


@bp.post("/api/grant-programs/<programId>/resume")
@require_roles(DEALER_ADMIN)
def resume_program(programId):
    rec = get_or_404(db.grant_programs, programId, ERR_GRANT_PROGRAM_NOT_FOUND, "GrantProgram")
    if rec["status"] != "PAUSED":
        raise state_forbids(ERR_PROGRAM_STATE_FORBIDS, "GrantProgram")
    rec["status"] = "OPEN"
    db.touch(rec)
    return ok(serialize(rec))


@bp.post("/api/grant-programs/<programId>/close")
@require_roles(DEALER_ADMIN)
def close_program(programId):
    rec = get_or_404(db.grant_programs, programId, ERR_GRANT_PROGRAM_NOT_FOUND, "GrantProgram")
    if rec["status"] not in ("OPEN", "PAUSED", "EXHAUSTED"):
        raise state_forbids(ERR_PROGRAM_STATE_FORBIDS, "GrantProgram")
    rec["status"] = "CLOSED"
    db.touch(rec)
    return ok(serialize(rec))


# --- GrantApplication -------------------------------------------------------

@bp.post("/api/grant-applications")
@require_roles(HOMEOWNER)
def create_application():
    vals = validate_body(get_json_body(), APPLICATION_SPEC)
    # body foreign keys (priority 4)
    project = get_or_404(db.projects, vals["project_id"], ERR_PROJECT_NOT_FOUND, "Project")
    program = get_or_404(db.grant_programs, vals["program_id"], ERR_GRANT_PROGRAM_NOT_FOUND, "GrantProgram")
    # state admission (priority 5): project must be mid-pipeline
    if project["status"] not in SUBMITTABLE_PROJECT_STATES:
        raise state_forbids(ERR_PROJECT_STATE_FORBIDS, "Project")
    # referenced program must be OPEN at submission (priority 8)
    if program["status"] != "OPEN":
        raise ApiError(ERR_PROGRAM_NOT_OPEN, 409, "Program is not OPEN for submission")
    # uniqueness / eligibility (priority 9)
    if any(
        a["project_id"] == project["id"] and a["program_id"] == program["id"] and a["status"] in ("SUBMITTED", "APPROVED")
        for a in db.grant_applications.values()
    ):
        raise ApiError(ERR_DUPLICATE_APPLICATION, 409, "A SUBMITTED or APPROVED application already exists for this project and program")
    if project["project_type"] not in program["eligible_project_types"]:
        raise ApiError(ERR_PROJECT_TYPE_INELIGIBLE, 422, "project_type is not eligible under this program")
    # temporal (priority 10): inclusive application window against the logical clock
    clock = db.now()
    if clock < program["application_open_date"] or clock > program["application_close_date"]:
        raise ApiError(ERR_APPLICATION_WINDOW_CLOSED, 422, "Logical clock is outside the program application window")
    # fiscal gates, always last (priority 11)
    if dec(vals["household_income"]) > dec(program["income_cap"]):
        raise ApiError(ERR_INCOME_ABOVE_CAP, 402, "household_income exceeds the program income_cap")
    rec = db.new_record({
        "project_id": project["id"],
        "program_id": program["id"],
        "household_income": vals["household_income"],
        "verified_income": None,
        "provisional_award": calc.grant_provisional_award(program, project),
        "final_award": None,
        "disbursed": None,
        "submitted_at": clock,
        "approved_at": None,
        "status": "SUBMITTED",
    })
    db.grant_applications[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.get("/api/grant-applications")
@require_roles(*ALL_ROLES)
def list_applications():
    return list_endpoint(db.grant_applications, {
        "project_id": "project_id", "program_id": "program_id", "status": "status",
    })


@bp.get("/api/grant-applications/<applicationId>")
@require_roles(*ALL_ROLES)
def get_application(applicationId):
    rec = get_or_404(db.grant_applications, applicationId, ERR_GRANT_APPLICATION_NOT_FOUND, "GrantApplication")
    return ok(serialize(rec))


def _recompute_project_posture(project):
    apps = [a for a in db.grant_applications.values() if a["project_id"] == project["id"]]
    project["funding_posture"] = calc.funding_posture(project, apps)
    db.touch(project)


@bp.post("/api/grant-applications/<applicationId>/approve")
@require_roles(GRANT_OFFICER)
def approve_application(applicationId):
    app = get_or_404(db.grant_applications, applicationId, ERR_GRANT_APPLICATION_NOT_FOUND, "GrantApplication")
    vals = validate_body(get_json_body(), {"verified_income": ("money", True, None)})
    # state admission (priority 5)
    if app["status"] != "SUBMITTED":
        raise state_forbids(ERR_APPLICATION_STATE_FORBIDS, "GrantApplication")
    program = db.grant_programs.get(app["program_id"])
    project = db.projects.get(app["project_id"])
    # priority 8: an already-submitted application may be approved while the
    # program is OPEN or EXHAUSTED (PAUSED / CLOSED are refused)
    if program is None or program["status"] not in ("OPEN", "EXHAUSTED"):
        raise ApiError(ERR_PROGRAM_NOT_OPEN, 409, "Program is not OPEN or EXHAUSTED")
    # fiscal gates (priority 11): verified income, then pool availability
    if dec(vals["verified_income"]) > dec(program["income_cap"]):
        raise ApiError(ERR_VERIFIED_INCOME_INELIGIBLE, 402, "verified_income exceeds the program income_cap")
    if dec(program["remaining_pool"]) <= 0:
        raise ApiError(ERR_GRANT_POOL_EXHAUSTED, 402, "Program funding pool is exhausted")
    app["verified_income"] = vals["verified_income"]
    app["approved_at"] = db.now()
    app["final_award"] = calc.grant_final_award(program, project)
    app["status"] = "APPROVED"
    db.touch(app)
    # pool debit; draining to exactly zero flips OPEN -> EXHAUSTED
    cascade.debit_program_pool(program, app["final_award"])
    if project is not None:
        _recompute_project_posture(project)
    return ok(serialize(app))


@bp.post("/api/grant-applications/<applicationId>/deny")
@require_roles(GRANT_OFFICER)
def deny_application(applicationId):
    app = get_or_404(db.grant_applications, applicationId, ERR_GRANT_APPLICATION_NOT_FOUND, "GrantApplication")
    validate_body(get_json_body(), {"denial_reason": ("string", True, None)})
    if app["status"] != "SUBMITTED":
        raise state_forbids(ERR_APPLICATION_STATE_FORBIDS, "GrantApplication")
    app["status"] = "DENIED"
    db.touch(app)
    return ok(serialize(app))


@bp.post("/api/grant-applications/<applicationId>/withdraw")
@require_roles(HOMEOWNER)
def withdraw_application(applicationId):
    app = get_or_404(db.grant_applications, applicationId, ERR_GRANT_APPLICATION_NOT_FOUND, "GrantApplication")
    # state admission (priority 5) before identity binding (priority 7)
    if app["status"] not in ("SUBMITTED", "APPROVED", "DISBURSED"):
        raise state_forbids(ERR_APPLICATION_STATE_FORBIDS, "GrantApplication")
    project = db.projects.get(app["project_id"])
    require_property_ownership(project["property_id"] if project else None)
    program = db.grant_programs.get(app["program_id"])
    if app["status"] == "SUBMITTED":
        app["status"] = "WITHDRAWN"
        db.touch(app)
    elif app["status"] == "APPROVED":
        app["status"] = "WITHDRAWN"
        db.touch(app)
        # compensating pool credit; reopens an EXHAUSTED program above zero
        if program is not None and app.get("final_award") is not None:
            cascade.credit_program_pool(program, app["final_award"])
        if project is not None:
            _recompute_project_posture(project)
    else:  # DISBURSED -> CLAWED_BACK
        app["status"] = "CLAWED_BACK"
        db.touch(app)
        if program is not None and app.get("disbursed") is not None:
            cascade.credit_program_pool(program, app["disbursed"])
        if project is not None:
            project["disbursed_grants"] = calc.money(dec(project["disbursed_grants"]) - dec(app["disbursed"]))
            if project["final_invoice"] is not None:
                project["homeowner_balance"] = calc.money(dec(project["final_invoice"]) - dec(project["disbursed_grants"]))
            _recompute_project_posture(project)
    return ok(serialize(app))
