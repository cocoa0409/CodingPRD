"""KitchenLayout endpoints: create/list/get/submit/approve/return-for-revision
(PRD 3.2)."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_HOOD_SPEC_INCONSISTENT,
    ERR_LAYOUT_EMPTY,
    ERR_LAYOUT_NOT_DRAFT,
    ERR_LAYOUT_NOT_SUBMITTED,
    HTTP_STATUS,
)
from middleware import require_roles
from response import success_object
from routes.common import (
    check_project_ownership,
    paginate,
    resolve_layout,
    resolve_project,
    serialize,
)
from services import workflow
from services.validate import json_body, opt_bool, req_str

bp = Blueprint("layouts", __name__)

LAYOUT_READ_ROLES = ("PlatformAdmin", "ProjectManager", "SalesRep", "KitchenDesigner", "Customer")


@bp.route("/design-build-projects/<id>/layouts", methods=["POST"])
@require_roles("KitchenDesigner")
def create_layout(id, _user_id=None, _role=None):
    project = resolve_project(id)
    body = json_body(required=True)
    layout = db.stamp_new({
        "project_id": project["id"],
        "layout_label": req_str(body, "layout_label"),
        "drawing_ref": req_str(body, "drawing_ref"),
        "hood_required": opt_bool(body, "hood_required", default=False),
        "revision_no": 1,
        "status": "DRAFT",
    })
    db.layouts[layout["id"]] = layout
    return success_object(serialize(layout), 201)


@bp.route("/design-build-projects/<id>/layouts", methods=["GET"])
@require_roles(*LAYOUT_READ_ROLES)
def list_layouts(id, _user_id=None, _role=None):
    project = resolve_project(id)
    check_project_ownership(_user_id, _role, project)
    status = request.args.get("status")
    records = [ly for ly in db.layouts.values() if ly["project_id"] == project["id"]]
    if status is not None:
        records = [ly for ly in records if ly["status"] == status]
    return paginate(records)


@bp.route("/design-build-projects/<id>/layouts/<layoutId>", methods=["GET"])
@require_roles(*LAYOUT_READ_ROLES)
def get_layout(id, layoutId, _user_id=None, _role=None):
    project = resolve_project(id)
    layout = resolve_layout(project, layoutId)
    check_project_ownership(_user_id, _role, project)
    return success_object(serialize(layout), 200)


@bp.route("/design-build-projects/<id>/layouts/<layoutId>/submit", methods=["POST"])
@require_roles("KitchenDesigner")
def submit_layout(id, layoutId, _user_id=None, _role=None):
    project = resolve_project(id)
    layout = resolve_layout(project, layoutId)
    # State legality first, then the structural checks (PRD 3.2 order).
    if layout["status"] != "DRAFT":
        raise ApiError(
            ERR_LAYOUT_NOT_DRAFT, HTTP_STATUS[ERR_LAYOUT_NOT_DRAFT],
            "Submit requires Layout in DRAFT",
        )
    items = [
        it for it in db.items.values()
        if it["layout_id"] == layout["id"] and it["status"] != "CANCELLED"
    ]
    if not items:
        raise ApiError(
            ERR_LAYOUT_EMPTY, HTTP_STATUS[ERR_LAYOUT_EMPTY],
            "Layout must reference at least one EquipmentItem before submit",
        )
    if layout["hood_required"] and not any(it["requires_hood"] for it in items):
        raise ApiError(
            ERR_HOOD_SPEC_INCONSISTENT, HTTP_STATUS[ERR_HOOD_SPEC_INCONSISTENT],
            "hood_required layout has no requires_hood EquipmentItem",
        )
    layout["status"] = "SUBMITTED"
    db.touch(layout)
    return success_object(serialize(layout), 200)


@bp.route("/design-build-projects/<id>/layouts/<layoutId>/approve", methods=["POST"])
@require_roles("ProjectManager")
def approve_layout(id, layoutId, _user_id=None, _role=None):
    project = resolve_project(id)
    layout = resolve_layout(project, layoutId)
    if layout["status"] != "SUBMITTED":
        raise ApiError(
            ERR_LAYOUT_NOT_SUBMITTED, HTTP_STATUS[ERR_LAYOUT_NOT_SUBMITTED],
            "Approve requires Layout in SUBMITTED",
        )
    layout["status"] = "APPROVED"
    db.touch(layout)
    workflow.supersede_sibling_layouts(project, layout)
    return success_object(serialize(layout), 200)


@bp.route("/design-build-projects/<id>/layouts/<layoutId>/return-for-revision", methods=["POST"])
@require_roles("ProjectManager")
def return_layout(id, layoutId, _user_id=None, _role=None):
    project = resolve_project(id)
    layout = resolve_layout(project, layoutId)
    if layout["status"] != "SUBMITTED":
        raise ApiError(
            ERR_LAYOUT_NOT_SUBMITTED, HTTP_STATUS[ERR_LAYOUT_NOT_SUBMITTED],
            "Return-for-revision requires Layout in SUBMITTED",
        )
    layout["status"] = "DRAFT"
    layout["revision_no"] = int(layout["revision_no"]) + 1
    db.touch(layout)
    return success_object(serialize(layout), 200)
