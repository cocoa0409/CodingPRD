"""ChangeOrder endpoints (PRD 3.8): proposal, homeowner approve/reject with the
chronological markup rule."""

from flask import Blueprint

import db
from errors import (
    ERR_CHANGE_ORDER_NOT_FOUND, ERR_CHANGE_ORDER_STATE_FORBIDS,
    ERR_PROJECT_NOT_FOUND, ERR_PROJECT_STATE_FORBIDS, invalid_request,
    state_forbids,
)
from middleware import HOMEOWNER, PROJECT_COORDINATOR, ALL_ROLES, require_roles
from response import ok
from routes.common import get_or_404, list_endpoint, require_property_ownership
from services import calc
from util import dec, get_json_body, money, serialize, validate_body

bp = Blueprint("change_orders", __name__)

CREATE_SPEC = {
    "project_id": ("string", True, None),
    "description": ("string", True, None),
    "amount": ("money", True, None),
}


def _recompute_project(project):
    approved = [c for c in db.change_orders.values() if c["project_id"] == project["id"] and c["status"] == "APPROVED"]
    project["approved_change_order_total"] = money(sum((dec(c["effective_amount"]) for c in approved), dec(0)))
    if project["contract_price"] is not None and project["status"] != "CLOSED":
        project["homeowner_balance"] = money(
            dec(project["contract_price"]) + dec(project["approved_change_order_total"]) - dec(project["disbursed_grants"])
        )
    apps = [a for a in db.grant_applications.values() if a["project_id"] == project["id"]]
    project["funding_posture"] = calc.funding_posture(project, apps)
    db.touch(project)


@bp.post("/api/change-orders")
@require_roles(PROJECT_COORDINATOR)
def create_change_order():
    vals = validate_body(get_json_body(), CREATE_SPEC)
    if dec(vals["amount"]) == 0:
        raise invalid_request("amount must be non-zero")
    project = get_or_404(db.projects, vals["project_id"], ERR_PROJECT_NOT_FOUND, "Project")
    # creation-time state gate (priority 5)
    if project["status"] in ("CLOSED", "CANCELLED"):
        raise state_forbids(ERR_PROJECT_STATE_FORBIDS, "Project")
    rec = db.new_record({
        "project_id": project["id"],
        "description": vals["description"],
        "amount": vals["amount"],
        "effective_amount": None,
        "approved_at": None,
        "status": "PROPOSED",
    })
    db.change_orders[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.get("/api/change-orders")
@require_roles(*ALL_ROLES)
def list_change_orders():
    return list_endpoint(db.change_orders, {"project_id": "project_id", "status": "status"})


@bp.get("/api/change-orders/<changeOrderId>")
@require_roles(*ALL_ROLES)
def get_change_order(changeOrderId):
    rec = get_or_404(db.change_orders, changeOrderId, ERR_CHANGE_ORDER_NOT_FOUND, "ChangeOrder")
    return ok(serialize(rec))


@bp.post("/api/change-orders/<changeOrderId>/approve")
@require_roles(HOMEOWNER)
def approve_change_order(changeOrderId):
    rec = get_or_404(db.change_orders, changeOrderId, ERR_CHANGE_ORDER_NOT_FOUND, "ChangeOrder")
    # state admission (priority 5): the order, then its project
    if rec["status"] != "PROPOSED":
        raise state_forbids(ERR_CHANGE_ORDER_STATE_FORBIDS, "ChangeOrder")
    project = db.projects.get(rec["project_id"])
    if project is None or project["status"] in ("CLOSED", "CANCELLED"):
        raise state_forbids(ERR_PROJECT_STATE_FORBIDS, "Project")
    # identity binding (priority 7): homeowner must own the property
    require_property_ownership(project["property_id"])
    rec["approved_at"] = db.now()
    # chronological markup rule: first APPROVED change order per project takes its
    # amount with no markup; every subsequent one takes amount * 1.10 (rhu 2dp)
    prior_approved = [
        c for c in db.change_orders.values()
        if c["project_id"] == rec["project_id"] and c["status"] == "APPROVED" and c["id"] != rec["id"]
    ]
    rec["effective_amount"] = calc.change_order_effective_amount(rec["amount"], is_first=not prior_approved)
    rec["status"] = "APPROVED"
    db.touch(rec)
    _recompute_project(project)
    return ok(serialize(rec))


@bp.post("/api/change-orders/<changeOrderId>/reject")
@require_roles(HOMEOWNER)
def reject_change_order(changeOrderId):
    rec = get_or_404(db.change_orders, changeOrderId, ERR_CHANGE_ORDER_NOT_FOUND, "ChangeOrder")
    if rec["status"] != "PROPOSED":
        raise state_forbids(ERR_CHANGE_ORDER_STATE_FORBIDS, "ChangeOrder")
    project = db.projects.get(rec["project_id"])
    require_property_ownership(project["property_id"] if project else None)
    rec["status"] = "REJECTED"
    db.touch(rec)
    return ok(serialize(rec))
