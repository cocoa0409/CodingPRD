"""StartupSession endpoints (PRD 3.7): schedule, complete (three-level
cascade: item STARTED + warranty REGISTERED, project warranty count,
COMMISSIONED bubble-up with service-agency handoff), void."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_DEMO_TOO_SHORT,
    ERR_ITEM_NOT_FOUND,
    ERR_ITEM_NOT_INSTALLED,
    ERR_SESSION_NOT_SCHEDULED,
    HTTP_STATUS,
)
from middleware import require_roles
from response import success_object
from routes.common import paginate, resolve_project, resolve_session, serialize
from services import workflow
from services.validate import json_body, req_int, req_str

bp = Blueprint("sessions", __name__)

SESSION_READ_ROLES = ("PlatformAdmin", "ProjectManager", "StartupTechnician")


@bp.route("/design-build-projects/<id>/startup-sessions", methods=["POST"])
@require_roles("StartupTechnician")
def create_session(id, _user_id=None, _role=None):
    project = resolve_project(id)
    body = json_body(required=True)
    item_id = req_str(body, "equipment_item_id")
    technician_name = req_str(body, "technician_name")
    demo_minutes = req_int(body, "demo_minutes")
    item = db.items.get(item_id)
    if item is None or item["project_id"] != project["id"]:
        raise ApiError(
            ERR_ITEM_NOT_FOUND, HTTP_STATUS[ERR_ITEM_NOT_FOUND],
            "EquipmentItem not found",
        )
    session = db.stamp_new({
        "project_id": project["id"],
        "equipment_item_id": item["id"],
        "technician_name": technician_name,
        "demo_minutes": demo_minutes,
        "warranty_registered": False,
        "status": "SCHEDULED",
    })
    db.sessions[session["id"]] = session
    return success_object(serialize(session), 201)


@bp.route("/design-build-projects/<id>/startup-sessions", methods=["GET"])
@require_roles(*SESSION_READ_ROLES)
def list_sessions(id, _user_id=None, _role=None):
    project = resolve_project(id)
    status = request.args.get("status")
    item_id = request.args.get("equipment_item_id")
    records = [s for s in db.sessions.values() if s["project_id"] == project["id"]]
    if status is not None:
        records = [s for s in records if s["status"] == status]
    if item_id is not None:
        records = [s for s in records if s["equipment_item_id"] == item_id]
    return paginate(records)


@bp.route("/design-build-projects/<id>/startup-sessions/<sessionId>", methods=["GET"])
@require_roles(*SESSION_READ_ROLES)
def get_session(id, sessionId, _user_id=None, _role=None):
    project = resolve_project(id)
    session = resolve_session(project, sessionId)
    return success_object(serialize(session), 200)


@bp.route("/design-build-projects/<id>/startup-sessions/<sessionId>/complete", methods=["POST"])
@require_roles("StartupTechnician")
def complete_session(id, sessionId, _user_id=None, _role=None):
    project = resolve_project(id)
    session = resolve_session(project, sessionId)
    # Guards in PRD 3.7 order: session SCHEDULED, item INSTALLED, demo >= 15.
    if session["status"] != "SCHEDULED":
        raise ApiError(
            ERR_SESSION_NOT_SCHEDULED, HTTP_STATUS[ERR_SESSION_NOT_SCHEDULED],
            "Complete requires StartupSession in SCHEDULED",
        )
    item = db.items.get(session["equipment_item_id"])
    if item is None or item["status"] != "INSTALLED":
        raise ApiError(
            ERR_ITEM_NOT_INSTALLED, HTTP_STATUS[ERR_ITEM_NOT_INSTALLED],
            "Startup complete requires EquipmentItem in INSTALLED",
        )
    if int(session["demo_minutes"]) < 15:
        raise ApiError(
            ERR_DEMO_TOO_SHORT, HTTP_STATUS[ERR_DEMO_TOO_SHORT],
            "demo_minutes < 15",
        )
    session["status"] = "COMPLETE"
    session["warranty_registered"] = True
    db.touch(session)
    item["status"] = "STARTED"
    item["warranty_status"] = "REGISTERED"
    db.touch(item)
    project["warranty_registered_count"] = int(project["warranty_registered_count"]) + 1
    db.touch(project)
    # Depth-3 cascade: all items STARTED + REGISTERED commissions the project,
    # which auto-opens a ServiceAssignment (deferred if no agency qualifies).
    workflow.commission_if_possible(project)
    return success_object(serialize(session), 200)


@bp.route("/design-build-projects/<id>/startup-sessions/<sessionId>/void", methods=["POST"])
@require_roles("StartupTechnician")
def void_session(id, sessionId, _user_id=None, _role=None):
    project = resolve_project(id)
    session = resolve_session(project, sessionId)
    if session["status"] != "SCHEDULED":
        raise ApiError(
            ERR_SESSION_NOT_SCHEDULED, HTTP_STATUS[ERR_SESSION_NOT_SCHEDULED],
            "Void requires StartupSession in SCHEDULED",
        )
    session["status"] = "VOID"
    db.touch(session)
    return success_object(serialize(session), 200)
