"""PermitApplication endpoints (PRD 3.3)."""

from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    ApiError, ERR_MODEL_DISCONTINUED, ERR_OPEN_PERMIT_EXISTS,
    ERR_PERMIT_NOT_FOUND, ERR_PERMIT_STATE_FORBIDS, ERR_PROJECT_NOT_FOUND,
    ERR_PROJECT_STATE_FORBIDS, state_forbids,
)
from middleware import PROJECT_COORDINATOR, REGULATOR, ALL_ROLES, require_roles
from response import ok
from routes.common import get_or_404, list_endpoint
from services import calc
from util import get_json_body, serialize, validate_body

bp = Blueprint("permits", __name__)

CREATE_SPEC = {
    "project_id": ("string", True, None),
    "ahj_name": ("string", True, None),
}

NON_TERMINAL_PERMIT = ("UNDER_REVIEW", "CORRECTIONS_REQUIRED", "APPROVED")


@bp.post("/api/permits")
@require_roles(PROJECT_COORDINATOR)
def create_permit():
    vals = validate_body(get_json_body(), CREATE_SPEC)
    project = get_or_404(db.projects, vals["project_id"], ERR_PROJECT_NOT_FOUND, "Project")
    # creation-time cross-entity state gate (priority 5)
    if project["status"] not in ("QUOTED", "PERMIT_APPROVED", "READY_FOR_INSTALL"):
        raise state_forbids(ERR_PROJECT_STATE_FORBIDS, "Project")
    # referenced model must still be ACTIVE at filing (priority 8)
    model = db.product_models.get(project["product_model_id"])
    if model is None or model["status"] != "ACTIVE":
        raise ApiError(ERR_MODEL_DISCONTINUED, 409, "Referenced product model is DISCONTINUED")
    # uniqueness (priority 9): one non-terminal permit per project
    if any(p["project_id"] == project["id"] and p["status"] in NON_TERMINAL_PERMIT for p in db.permits.values()):
        raise ApiError(ERR_OPEN_PERMIT_EXISTS, 409, "Project already has a non-terminal permit application")
    survey = db.surveys.get(project["survey_id"])
    fee = calc.permit_fee(project["contract_price"], survey["floors_served"])
    rec = db.new_record({
        "project_id": project["id"],
        "ahj_name": vals["ahj_name"],
        "fee": fee,
        "revision_count": 0,
        "approved_date": None,
        "valid_through": None,
        "status": "UNDER_REVIEW",
    })
    db.permits[rec["id"]] = rec
    # only a QUOTED project moves; PERMIT_APPROVED / READY_FOR_INSTALL stay in place
    if project["status"] == "QUOTED":
        project["status"] = "PERMIT_IN_PROGRESS"
        db.touch(project)
    return ok(serialize(rec), 201)


@bp.get("/api/permits")
@require_roles(*ALL_ROLES)
def list_permits():
    return list_endpoint(db.permits, {"project_id": "project_id", "status": "status"})


@bp.get("/api/permits/<permitId>")
@require_roles(*ALL_ROLES)
def get_permit(permitId):
    rec = get_or_404(db.permits, permitId, ERR_PERMIT_NOT_FOUND, "Permit")
    return ok(serialize(rec))


@bp.post("/api/permits/<permitId>/request-corrections")
@require_roles(REGULATOR)
def request_corrections(permitId):
    permit = get_or_404(db.permits, permitId, ERR_PERMIT_NOT_FOUND, "Permit")
    validate_body(get_json_body(), {"correction_notes": ("string", True, None)})
    if permit["status"] != "UNDER_REVIEW":
        raise state_forbids(ERR_PERMIT_STATE_FORBIDS, "Permit")
    permit["status"] = "CORRECTIONS_REQUIRED"
    permit["revision_count"] += 1
    db.touch(permit)
    return ok(serialize(permit))


@bp.post("/api/permits/<permitId>/resubmit")
@require_roles(PROJECT_COORDINATOR)
def resubmit_permit(permitId):
    permit = get_or_404(db.permits, permitId, ERR_PERMIT_NOT_FOUND, "Permit")
    if permit["status"] != "CORRECTIONS_REQUIRED":
        raise state_forbids(ERR_PERMIT_STATE_FORBIDS, "Permit")
    permit["status"] = "UNDER_REVIEW"
    db.touch(permit)
    return ok(serialize(permit))


@bp.post("/api/permits/<permitId>/approve")
@require_roles(REGULATOR)
def approve_permit(permitId):
    permit = get_or_404(db.permits, permitId, ERR_PERMIT_NOT_FOUND, "Permit")
    if permit["status"] != "UNDER_REVIEW":
        raise state_forbids(ERR_PERMIT_STATE_FORBIDS, "Permit")
    # cross-entity gate (priority 5): project must be PERMIT_IN_PROGRESS
    project = db.projects.get(permit["project_id"])
    if project is None or project["status"] != "PERMIT_IN_PROGRESS":
        raise state_forbids(ERR_PROJECT_STATE_FORBIDS, "Project")
    permit["approved_date"] = db.now()
    permit["valid_through"] = db.now() + timedelta(days=calc.PERMIT_VALID_DAYS)
    permit["status"] = "APPROVED"
    db.touch(permit)
    # side effect: project advances; auto READY_FOR_INSTALL when no structural work
    project["status"] = "PERMIT_APPROVED"
    if not project["requires_structural"]:
        project["status"] = "READY_FOR_INSTALL"
    db.touch(project)
    return ok(serialize(permit))


@bp.post("/api/permits/<permitId>/deny")
@require_roles(REGULATOR)
def deny_permit(permitId):
    permit = get_or_404(db.permits, permitId, ERR_PERMIT_NOT_FOUND, "Permit")
    validate_body(get_json_body(), {"denial_reason": ("string", True, None)})
    if permit["status"] != "UNDER_REVIEW":
        raise state_forbids(ERR_PERMIT_STATE_FORBIDS, "Permit")
    permit["status"] = "DENIED"
    db.touch(permit)
    # revision loop: drop the project back to QUOTED when it was waiting on this permit
    project = db.projects.get(permit["project_id"])
    if project is not None and project["status"] == "PERMIT_IN_PROGRESS":
        project["status"] = "QUOTED"
        db.touch(project)
    return ok(serialize(permit))
