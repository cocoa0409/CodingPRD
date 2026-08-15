"""PunchListItem endpoints (PRD 3.8)."""

from __future__ import annotations

from flask import Blueprint, request

import db
from middleware import require_roles
from response import success_object
from routes.common import (
    check_project_ownership,
    paginate,
    resolve_project,
    resolve_punch,
    serialize,
)
from services.validate import json_body, req_enum, req_str

bp = Blueprint("punch", __name__)

SEVERITIES = ("COSMETIC", "FUNCTIONAL", "LIFE_SAFETY")
PUNCH_READ_ROLES = ("PlatformAdmin", "ProjectManager", "Customer")


@bp.route("/design-build-projects/<id>/punch-list-items", methods=["POST"])
@require_roles("ProjectManager", "Customer")
def create_punch(id, _user_id=None, _role=None):
    project = resolve_project(id)
    check_project_ownership(_user_id, _role, project)
    body = json_body(required=True)
    item = db.stamp_new({
        "project_id": project["id"],
        "description": req_str(body, "description"),
        "severity": req_enum(body, "severity", SEVERITIES),
        "status": "OPEN",
    })
    db.punch_items[item["id"]] = item
    return success_object(serialize(item), 201)


@bp.route("/design-build-projects/<id>/punch-list-items", methods=["GET"])
@require_roles(*PUNCH_READ_ROLES)
def list_punch(id, _user_id=None, _role=None):
    project = resolve_project(id)
    check_project_ownership(_user_id, _role, project)
    status = request.args.get("status")
    severity = request.args.get("severity")
    records = [p for p in db.punch_items.values() if p["project_id"] == project["id"]]
    if status is not None:
        records = [p for p in records if p["status"] == status]
    if severity is not None:
        records = [p for p in records if p["severity"] == severity]
    return paginate(records)


@bp.route("/design-build-projects/<id>/punch-list-items/<itemId>", methods=["GET"])
@require_roles(*PUNCH_READ_ROLES)
def get_punch(id, itemId, _user_id=None, _role=None):
    project = resolve_project(id)
    item = resolve_punch(project, itemId)
    check_project_ownership(_user_id, _role, project)
    return success_object(serialize(item), 200)


@bp.route("/design-build-projects/<id>/punch-list-items/<itemId>/verify", methods=["POST"])
@require_roles("ProjectManager")
def verify_punch(id, itemId, _user_id=None, _role=None):
    project = resolve_project(id)
    item = resolve_punch(project, itemId)
    # OPEN -> VERIFIED; no catalogued error exists for other start states, so
    # terminal items are returned unchanged (no transitions out of terminal).
    if item["status"] == "OPEN":
        item["status"] = "VERIFIED"
        db.touch(item)
    return success_object(serialize(item), 200)


@bp.route("/design-build-projects/<id>/punch-list-items/<itemId>/void", methods=["POST"])
@require_roles("ProjectManager")
def void_punch(id, itemId, _user_id=None, _role=None):
    project = resolve_project(id)
    item = resolve_punch(project, itemId)
    if item["status"] == "OPEN":
        item["status"] = "VOID"
        db.touch(item)
    return success_object(serialize(item), 200)
