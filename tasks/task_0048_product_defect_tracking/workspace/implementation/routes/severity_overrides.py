"""SeverityOverride endpoints."""

from __future__ import annotations

from flask import Blueprint, g

import db
from config import (
    DEFECT_CLOSED, SEVERITIES, SO_PENDING, SO_APPROVED, SO_REJECTED,
    ROLE_DEVELOPER, ROLE_QA_ENGINEER, ROLE_TRIAGE_MANAGER, ROLE_ANY,
)
from errors import (
    AppError, ERR_DEFECT_CLOSED, ERR_OVERRIDE_APPROVER_NOT_INDEPENDENT,
    ERR_OVERRIDE_NO_CHANGE, ERR_OVERRIDE_NOT_PENDING,
)
from middleware import require_role
from response import success
from services.audit import append_audit
from services.defect_logic import recompute_score_and_due
from services.serializers import severity_override_dto
from services.validators import (
    check_version, find_defect_or_404, find_override_or_404, find_project_or_404,
    ensure_project_active, get_json, require_enum, require_str,
)

bp = Blueprint("severity_overrides", __name__)


@bp.post("/defects/<defect_id>/severity-overrides")
def request_severity_override(defect_id):
    require_role(ROLE_DEVELOPER, ROLE_QA_ENGINEER, ROLE_TRIAGE_MANAGER)
    body = get_json()
    d = find_defect_or_404(defect_id)
    project = find_project_or_404(d["project_id"])
    ensure_project_active(project)

    requested_severity = require_enum(body, "requested_severity", SEVERITIES)
    justification = require_str(body, "justification")

    if d["status"] == DEFECT_CLOSED:
        raise AppError(ERR_DEFECT_CLOSED, "Cannot override a closed defect.", 409)
    if requested_severity == d["effective_severity"]:
        raise AppError(ERR_OVERRIDE_NO_CHANGE,
                       "requested_severity equals current effective_severity.", 400)

    row = db.insert("severity_overrides", {
        "defect_id": defect_id,
        "requested_severity": requested_severity,
        "justification": justification,
        "requested_by": g.user_id,
        "approved_by": None,
        "status": SO_PENDING,
    })
    return success(severity_override_dto(row), 201)


@bp.post("/severity-overrides/<override_id>/approve")
def approve_override(override_id):
    require_role(ROLE_TRIAGE_MANAGER)
    body = get_json()
    so = find_override_or_404(override_id)
    d = find_defect_or_404(so["defect_id"])
    project = find_project_or_404(d["project_id"])
    ensure_project_active(project)

    if so["status"] != SO_PENDING:
        raise AppError(ERR_OVERRIDE_NOT_PENDING,
                       f"Override status is {so['status']}", 409)
    if d["status"] == DEFECT_CLOSED:
        raise AppError(ERR_DEFECT_CLOSED, "Defect is closed.", 409)
    if g.user_id == so["requested_by"]:
        raise AppError(ERR_OVERRIDE_APPROVER_NOT_INDEPENDENT,
                       "Approver cannot be the requester.", 403)
    check_version(body, so)

    old_eff = d["effective_severity"]
    new_eff = so["requested_severity"]
    d["effective_severity"] = new_eff
    # Recompute priority_score and due dates against ORIGINAL report_clock_minute
    recompute_score_and_due(d, project_clock=project["clock_minute"])
    db.update("defects", d["id"], d, bump=True)

    db.update("severity_overrides", override_id, {
        "status": SO_APPROVED,
        "approved_by": g.user_id,
    }, bump=True)

    append_audit(
        defect_id=d["id"],
        event_type="SEVERITY_CHANGE",
        actor_id=g.user_id,
        from_value=old_eff,
        to_value=new_eff,
        at_minute=project["clock_minute"],
    )
    updated = db.find_by_id("severity_overrides", override_id)
    return success(severity_override_dto(updated))


@bp.post("/severity-overrides/<override_id>/reject")
def reject_override(override_id):
    require_role(ROLE_TRIAGE_MANAGER)
    body = get_json()
    so = find_override_or_404(override_id)
    d = find_defect_or_404(so["defect_id"])
    project = find_project_or_404(d["project_id"])
    ensure_project_active(project)

    if so["status"] != SO_PENDING:
        raise AppError(ERR_OVERRIDE_NOT_PENDING,
                       f"Override status is {so['status']}", 409)
    if d["status"] == DEFECT_CLOSED:
        raise AppError(ERR_DEFECT_CLOSED, "Defect is closed.", 409)
    if g.user_id == so["requested_by"]:
        raise AppError(ERR_OVERRIDE_APPROVER_NOT_INDEPENDENT,
                       "Rejecter cannot be the requester.", 403)
    check_version(body, so)

    db.update("severity_overrides", override_id, {"status": SO_REJECTED}, bump=True)

    append_audit(
        defect_id=d["id"],
        event_type="SEVERITY_CHANGE",
        actor_id=g.user_id,
        from_value=d["effective_severity"],
        to_value=d["effective_severity"],
        at_minute=project["clock_minute"],
        external_payload={"override_id": override_id, "decision": SO_REJECTED},
    )
    updated = db.find_by_id("severity_overrides", override_id)
    return success(severity_override_dto(updated))


@bp.get("/severity-overrides/<override_id>")
def get_override(override_id):
    require_role(ROLE_ANY)
    so = find_override_or_404(override_id)
    return success(severity_override_dto(so))
