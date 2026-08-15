"""CommissioningChecklist endpoints."""
from flask import Blueprint, g

import db
from errors import (ApiError, ERR_ALIGNMENT_OUTSTANDING, ERR_CHECKLIST_EXISTS,
                    ERR_CHECKLIST_INCOMPLETE, ERR_INVALID_STATE, ERR_NOT_FOUND,
                    ERR_VALIDATION)
from helpers import checklist_or_404, project_or_404, sorted_items, touch
from middleware import ROLES, require_roles
from response import success, success_list
from serialize import checklist_json
from util import fmt_clock, new_id, now_iso
from validators import get_body, pagination, req_str

bp = Blueprint("commissioning_checklists", __name__)


def _checked_required_count(items):
    return sum(1 for it in items if it.get("required") is True and it.get("checked") is True)


@bp.post("/v1/commissioning-checklists")
@require_roles("ProjectManager")
def create_checklist():
    body = get_body()
    pid = body.get("project_id")
    project = project_or_404(pid) if isinstance(pid, str) else None
    # state gate (priority 5): creation requires INSTALLING or COMMISSIONING
    if project is not None and project["work_status"] not in ("INSTALLING", "COMMISSIONING"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "checklist creation requires INSTALLING or COMMISSIONING phase")
    # schema (priority 7)
    req_str(body, "project_id")
    raw_items = body.get("items")
    if not isinstance(raw_items, list):
        raise ApiError(ERR_VALIDATION, 400, "'items': must be an array")
    items = []
    for idx, it in enumerate(raw_items):
        if not isinstance(it, dict):
            raise ApiError(ERR_VALIDATION, 400, f"'items[{idx}]': must be an object")
        if not isinstance(it.get("item_key"), str) or it.get("item_key") == "":
            raise ApiError(ERR_VALIDATION, 400, f"'items[{idx}].item_key': must be a non-empty string")
        if not isinstance(it.get("description"), str):
            raise ApiError(ERR_VALIDATION, 400, f"'items[{idx}].description': must be a string")
        if not isinstance(it.get("required"), bool):
            raise ApiError(ERR_VALIDATION, 400, f"'items[{idx}].required': must be a boolean")
        items.append({
            "item_key": it["item_key"],
            "description": it["description"],
            "required": it["required"],
            "checked": False,
            "checked_by_user_id": None,
            "checked_at": None,
        })
    # singleton (priority 17): at most one non-terminal checklist per project
    if any(c["project_id"] == project["id"] and c["status"] in ("IN_PROGRESS", "SUBMITTED")
           for c in db.checklists.values()):
        raise ApiError(ERR_CHECKLIST_EXISTS, 409,
                       "a non-terminal commissioning checklist already exists for the project")
    ts = now_iso()
    c = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "project_id": project["id"],
        "items": items,
        "required_count": sum(1 for it in items if it["required"]),
        "checked_required_count": 0,
        "status": "IN_PROGRESS",
        "signed_off_by_user_id": None,
        "_seq": db.next_seq(),
    }
    db.checklists[c["id"]] = c
    return success(checklist_json(c), 201)


@bp.get("/v1/projects/<pid>/commissioning-checklists")
@require_roles(*ROLES)
def list_checklists(pid):
    project_or_404(pid)
    limit, offset = pagination()
    items = sorted_items(c for c in db.checklists.values() if c["project_id"] == pid)
    total = len(items)
    return success_list([checklist_json(c) for c in items[offset:offset + limit]],
                        limit, offset, total)


@bp.post("/v1/commissioning-checklists/<cid>/check-item")
@require_roles("SiteSupervisor")
def check_item(cid):
    c = checklist_or_404(cid)
    body = get_body()
    # existence (priority 3): a supplied item_key must resolve to an item
    item = None
    if isinstance(body.get("item_key"), str):
        item = next((it for it in c["items"] if it["item_key"] == body["item_key"]), None)
        if item is None:
            raise ApiError(ERR_NOT_FOUND, 404, "unknown checklist item_key")
    # state (priority 5)
    if c["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "items can only be checked while the checklist is IN_PROGRESS")
    # schema (priority 7)
    req_str(body, "item_key")
    item["checked"] = True
    item["checked_by_user_id"] = g.user_id
    item["checked_at"] = fmt_clock(db.clock_now())
    c["checked_required_count"] = _checked_required_count(c["items"])
    touch(c)
    return success(checklist_json(c))


@bp.post("/v1/commissioning-checklists/<cid>/submit")
@require_roles("ProjectManager")
def submit_checklist(cid):
    c = checklist_or_404(cid)
    # state (priority 5): checklist IN_PROGRESS and project in COMMISSIONING
    if c["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only an IN_PROGRESS checklist can be submitted")
    project = db.projects[c["project_id"]]
    if project["work_status"] != "COMMISSIONING":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "checklist submission requires the project to be COMMISSIONING")
    # alignment gate (priority 14)
    records = [a for a in db.alignment_records.values() if a["project_id"] == c["project_id"]]
    has_pass = any(a["status"] == "ACCEPTED" and a["verdict"] == "PASS" for a in records)
    any_recorded = any(a["status"] == "RECORDED" for a in records)
    if not has_pass or any_recorded:
        raise ApiError(ERR_ALIGNMENT_OUTSTANDING, 409,
                       "alignment gate unmet: need an ACCEPTED PASS record and no RECORDED records")
    # completeness (priority 21)
    if c["checked_required_count"] != c["required_count"]:
        raise ApiError(ERR_CHECKLIST_INCOMPLETE, 422,
                       "not all required checklist items are checked")
    c["status"] = "SUBMITTED"
    touch(c)
    return success(checklist_json(c))


@bp.post("/v1/commissioning-checklists/<cid>/sign-off")
@require_roles("CustomerRep")
def sign_off_checklist(cid):
    c = checklist_or_404(cid)
    if c["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a SUBMITTED checklist can be signed off")
    body = get_body()
    note = body.get("signoff_note")
    if note is not None and not isinstance(note, str):
        raise ApiError(ERR_VALIDATION, 400, "'signoff_note': must be a string")
    c["status"] = "SIGNED_OFF"
    c["signed_off_by_user_id"] = g.user_id
    touch(c)
    # sign-off mutates the project (PRD 3.7)
    touch(db.projects[c["project_id"]])
    return success(checklist_json(c))
