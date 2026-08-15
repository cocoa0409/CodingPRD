"""Production milestones: list, get, submit, verify, reject."""

from flask import Blueprint, request

from db import public, store, touch
from errors import ApiError
from middleware import (
    ALL_ROLES,
    body_json,
    get_or_404,
    paginate,
    req_str,
    require_roles,
    sorted_created,
)
from response import success_list, success_object

bp = Blueprint("milestones", __name__)


def _get_milestone(milestoneId):
    return get_or_404(
        store.milestones, milestoneId, "ERR_MILESTONE_NOT_FOUND", "ProductionMilestone"
    )


def _po_of(milestone):
    return store.purchase_orders.get(milestone["po_id"])


@bp.route("/sourcing/milestones", methods=["GET"])
def list_milestones():
    require_roles(*ALL_ROLES)
    items = list(store.milestones.values())
    po_id = request.args.get("po_id")
    status = request.args.get("status")
    if po_id is not None:
        items = [m for m in items if m["po_id"] == po_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    items = sorted_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([public(m) for m in page], limit, offset, total)


@bp.route("/sourcing/milestones/<milestoneId>", methods=["GET"])
def get_milestone(milestoneId):
    require_roles(*ALL_ROLES)
    return success_object(public(_get_milestone(milestoneId)))


@bp.route("/sourcing/milestones/<milestoneId>/submit", methods=["POST"])
def submit_milestone(milestoneId):
    uid, _ = require_roles("FactoryRep")
    milestone = _get_milestone(milestoneId)
    data = body_json()
    evidence_note = req_str(data, "evidence_note")
    po = _po_of(milestone)
    if po is None or po["factory_id"] != uid:
        raise ApiError(
            "ERR_OWNERSHIP_SCOPE_VIOLATION",
            "Caller does not belong to the purchase order's factory",
            403,
        )
    if milestone["status"] not in ("PLANNED", "REJECTED"):
        raise ApiError(
            "ERR_MILESTONE_NOT_SUBMITTABLE",
            "Milestone is not PLANNED or REJECTED",
            409,
        )
    if po["status"] != "ACTIVE":
        raise ApiError("ERR_PO_NOT_ACTIVE", "PurchaseOrder is not ACTIVE", 409)
    if not po["milestone_plan_locked"]:
        raise ApiError(
            "ERR_MILESTONE_PLAN_INCOMPLETE",
            "Milestone plan is not locked (weights do not sum to 100)",
            409,
        )
    milestone["status"] = "SUBMITTED"
    milestone["evidence_note"] = evidence_note
    touch(milestone)
    if po["production_status"] == "PLACED":
        po["production_status"] = "IN_PRODUCTION"
        touch(po)
    return success_object(public(milestone))


@bp.route("/sourcing/milestones/<milestoneId>/verify", methods=["POST"])
def verify_milestone(milestoneId):
    uid, _ = require_roles("SourcingAgent")
    milestone = _get_milestone(milestoneId)
    po = _po_of(milestone)
    if po is None or po["assigned_agent_id"] != uid:
        raise ApiError(
            "ERR_OWNERSHIP_SCOPE_VIOLATION",
            "Caller is not the assigned agent for this purchase order",
            403,
        )
    if milestone["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_MILESTONE_NOT_VERIFIABLE", "Milestone is not SUBMITTED", 409
        )
    if po["status"] != "ACTIVE":
        raise ApiError("ERR_PO_NOT_ACTIVE", "PurchaseOrder is not ACTIVE", 409)
    milestone["status"] = "VERIFIED"
    touch(milestone)
    po["progress_pct"] = sum(
        m["weight_pct"]
        for m in store.milestones.values()
        if m["po_id"] == po["id"] and m["status"] == "VERIFIED"
    )
    po_milestones = [m for m in store.milestones.values() if m["po_id"] == po["id"]]
    if po_milestones and all(m["status"] == "VERIFIED" for m in po_milestones):
        po["production_status"] = "PRODUCTION_COMPLETE"
    touch(po)
    return success_object(public(milestone))


@bp.route("/sourcing/milestones/<milestoneId>/reject", methods=["POST"])
def reject_milestone(milestoneId):
    uid, _ = require_roles("SourcingAgent")
    milestone = _get_milestone(milestoneId)
    po = _po_of(milestone)
    if po is None or po["assigned_agent_id"] != uid:
        raise ApiError(
            "ERR_OWNERSHIP_SCOPE_VIOLATION",
            "Caller is not the assigned agent for this purchase order",
            403,
        )
    if milestone["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_MILESTONE_NOT_VERIFIABLE", "Milestone is not SUBMITTED", 409
        )
    milestone["status"] = "REJECTED"
    touch(milestone)
    return success_object(public(milestone))
