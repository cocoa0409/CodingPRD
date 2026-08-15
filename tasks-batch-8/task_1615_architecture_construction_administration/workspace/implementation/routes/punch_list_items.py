"""PunchListItem endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_PUNCH_ITEM_INVALID_STATE,
    ERR_PUNCH_VISIT_INVALID,
    ERR_PROJECT_NOT_ACTIVE,
)
from middleware import get_user_context, require_role, get_body
from response import success_object, success_list
from services.helpers import (
    base_entity, touch, paginate, get_project, get_punch_item, get_site_visit,
    req_str,
)
from services.lifecycle import require_project_active, check_counterparty

bp = Blueprint("punch_list_items", __name__)

ALL_ROLES = ("FirmAdmin", "ArchitectCA", "Contractor", "Owner")


@bp.post("/ca/punch-list-items")
def create_punch_list_item():
    _, role = get_user_context()
    require_role(role, ("ArchitectCA",))
    body = get_body(required=True)
    project_id = req_str(body, "project_id")
    raised_visit_id = req_str(body, "raised_visit_id")
    description = req_str(body, "description")
    location = req_str(body, "location")

    project = get_project(project_id)
    visit = get_site_visit(raised_visit_id)
    require_project_active(project)

    if (
        visit["project_id"] != project_id
        or visit["purpose"] != "PUNCH_INSPECTION"
        or visit["status"] != "REPORT_ISSUED"
    ):
        raise ApiError(
            ERR_PUNCH_VISIT_INVALID,
            "raised_visit_id is not a PUNCH_INSPECTION visit in REPORT_ISSUED on the same project",
            422,
        )

    item = base_entity()
    item.update({
        "project_id": project_id,
        "raised_visit_id": raised_visit_id,
        "description": description,
        "location": location,
        "reopen_count": 0,
        "status": "OPEN",
    })
    db.punch_list_items[item["id"]] = item
    return success_object(item, 201)


@bp.get("/ca/punch-list-items")
def list_punch_list_items():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.punch_list_items.values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [i for i in items if i["project_id"] == project_id]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    raised = request.args.get("raised_visit_id")
    if raised is not None:
        items = [i for i in items if i["raised_visit_id"] == raised]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/ca/punch-list-items/<iid>")
def get_one_punch_list_item(iid):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    return success_object(get_punch_item(iid))


@bp.post("/ca/punch-list-items/<iid>/claim-complete")
def claim_punch_item_complete(iid):
    user_id, role = get_user_context()
    require_role(role, ("Contractor",))
    item = get_punch_item(iid)
    project = db.projects[item["project_id"]]
    check_counterparty(role, user_id, project)
    if item["status"] not in ("OPEN", "REOPENED"):
        raise ApiError(
            ERR_PUNCH_ITEM_INVALID_STATE,
            "punch claim requires OPEN or REOPENED",
            409,
        )
    item["status"] = "CLAIMED_COMPLETE"
    touch(item)
    return success_object(item)


@bp.post("/ca/punch-list-items/<iid>/verify")
def verify_punch_item(iid):
    _, role = get_user_context()
    require_role(role, ("ArchitectCA",))
    item = get_punch_item(iid)
    if item["status"] != "CLAIMED_COMPLETE":
        raise ApiError(
            ERR_PUNCH_ITEM_INVALID_STATE,
            "punch verify requires CLAIMED_COMPLETE",
            409,
        )
    item["status"] = "VERIFIED"
    touch(item)
    return success_object(item)


@bp.post("/ca/punch-list-items/<iid>/reopen")
def reopen_punch_item(iid):
    _, role = get_user_context()
    require_role(role, ("ArchitectCA",))
    body = get_body(required=True)
    if "reason" not in body or not isinstance(body["reason"], str):
        from services.helpers import invalid
        invalid("reason is required and must be a string")
    item = get_punch_item(iid)
    if item["status"] not in ("CLAIMED_COMPLETE", "VERIFIED"):
        raise ApiError(
            ERR_PUNCH_ITEM_INVALID_STATE,
            "punch reopen requires CLAIMED_COMPLETE or VERIFIED",
            409,
        )
    if item["status"] == "VERIFIED":
        project = db.projects[item["project_id"]]
        if project["status"] not in ("ACTIVE", "SUBSTANTIAL_COMPLETION_ACHIEVED"):
            raise ApiError(
                ERR_PROJECT_NOT_ACTIVE,
                "VERIFIED punch-item reopen requires the project ACTIVE or SUBSTANTIAL_COMPLETION_ACHIEVED",
                409,
            )
    item["status"] = "REOPENED"
    item["reopen_count"] += 1
    touch(item)
    return success_object(item)
