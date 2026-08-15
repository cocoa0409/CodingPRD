"""Rfi endpoints."""

from flask import Blueprint, request

import db
from errors import ApiError, ERR_RFI_INVALID_STATE
from middleware import get_user_context, require_role, get_body
from response import success_object, success_list
from services import calcs
from services.helpers import (
    base_entity, touch, paginate, get_project, get_rfi,
    req_str, opt_bool,
)
from services.lifecycle import require_project_active, check_counterparty
from routes.submittals import _late_credit_days

bp = Blueprint("rfis", __name__)

ALL_ROLES = ("FirmAdmin", "ArchitectCA", "Contractor", "Owner")


@bp.post("/ca/rfis")
def create_rfi():
    user_id, role = get_user_context()
    require_role(role, ("Contractor",))
    body = get_body(required=True)
    project_id = req_str(body, "project_id")
    question = req_str(body, "question")
    cost_impact_flag = opt_bool(body, "cost_impact_flag", False)

    project = get_project(project_id)
    check_counterparty(role, user_id, project)
    require_project_active(project)

    received = db.now_iso()
    rfi = base_entity()
    rfi.update({
        "project_id": project_id,
        "question": question,
        "cost_impact_flag": cost_impact_flag,
        "received_at": received,
        "due_at": db.add_days_to_dt(received, project["review_window_days_rfi"]),
        "answered_at": None,
        "answer_text": None,
        "credited_delay_days": 0,
        "status": "OPEN",
    })
    db.rfis[rfi["id"]] = rfi
    return success_object(rfi, 201)


@bp.get("/ca/rfis")
def list_rfis():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.rfis.values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [r for r in items if r["project_id"] == project_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/ca/rfis/<rid>")
def get_one_rfi(rid):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    return success_object(get_rfi(rid))


def answer_rfi_with_clock(rfi: dict, answered_at: str):
    """Shared late-credit + recompute chain when an RFI enters ANSWERED."""
    rfi["answered_at"] = answered_at
    rfi["credited_delay_days"] = _late_credit_days(answered_at, rfi["due_at"])
    rfi["status"] = "ANSWERED"
    project = db.projects[rfi["project_id"]]
    calcs.recompute_excusable_delay(project)
    calcs.recompute_project_dependents(project, delay_changed=True)


@bp.post("/ca/rfis/<rid>/answer")
def answer_rfi(rid):
    _, role = get_user_context()
    require_role(role, ("ArchitectCA",))
    body = get_body(required=True)
    answer_text = req_str(body, "answer_text")
    requires_clarification_drawing = opt_bool(body, "requires_clarification_drawing", False)

    rfi = get_rfi(rid)
    if rfi["status"] != "OPEN":
        raise ApiError(ERR_RFI_INVALID_STATE, "rfi answer requires OPEN", 409)

    rfi["answer_text"] = answer_text
    if requires_clarification_drawing:
        rfi["status"] = "CLARIFICATION_PENDING"
        touch(rfi)
    else:
        answer_rfi_with_clock(rfi, db.now_iso())
        touch(rfi)
    return success_object(rfi)


@bp.post("/ca/rfis/<rid>/close")
def close_rfi(rid):
    user_id, role = get_user_context()
    require_role(role, ("Contractor",))
    rfi = get_rfi(rid)
    project = db.projects[rfi["project_id"]]
    check_counterparty(role, user_id, project)
    if rfi["status"] != "ANSWERED":
        raise ApiError(ERR_RFI_INVALID_STATE, "rfi close requires ANSWERED", 409)
    rfi["status"] = "CLOSED"
    touch(rfi)
    return success_object(rfi)


@bp.post("/ca/rfis/<rid>/withdraw")
def withdraw_rfi(rid):
    user_id, role = get_user_context()
    require_role(role, ("Contractor",))
    rfi = get_rfi(rid)
    project = db.projects[rfi["project_id"]]
    check_counterparty(role, user_id, project)
    if rfi["status"] != "OPEN":
        raise ApiError(ERR_RFI_INVALID_STATE, "rfi withdraw requires OPEN", 409)
    rfi["status"] = "WITHDRAWN"
    touch(rfi)
    return success_object(rfi)
