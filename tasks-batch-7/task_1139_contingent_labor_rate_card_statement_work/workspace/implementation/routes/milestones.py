from flask import Blueprint

from db import stamp_new, store, touch
from envelope import ok, ok_list
from errors import (
    ERR_BUDGET_EXCEEDED,
    ERR_ENGAGEMENT_NOT_ACTIVE,
    ERR_ENGAGEMENT_TYPE_MISMATCH,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SUPPLIER_SUSPENDED,
    raise_err,
)
from security import ALL_READ, require_roles
from services import run_billable_event
from validators import get_body, opt_str, paginate, req_date, req_int, req_str
import serializers

bp = Blueprint("milestones", __name__)


def _get_engagement(engagement_id):
    eng = store.engagements.get(engagement_id)
    if eng is None:
        raise_err(ERR_NOT_FOUND, f"Engagement {engagement_id} not found.")
    return eng


def _get_milestone(milestone_id):
    m = store.milestones.get(milestone_id)
    if m is None:
        raise_err(ERR_NOT_FOUND, f"Milestone {milestone_id} not found.")
    return m


@bp.post("/v1/engagements/<engagement_id>/milestones")
def create_milestone(engagement_id):
    require_roles("HiringManager")
    body = get_body()
    name = req_str(body, "name")
    amount = req_int(body, "amount_cents")
    due = req_date(body, "due_date")
    eng = _get_engagement(engagement_id)
    if eng["status"] not in ("OPEN", "FILLING", "ACTIVE"):
        raise_err(
            ERR_INVALID_STATE,
            "Milestones can only be created while the engagement is OPEN, FILLING or ACTIVE.",
        )
    if eng["engagement_type"] != "SOW":
        raise_err(
            ERR_ENGAGEMENT_TYPE_MISMATCH,
            "Milestones may only be created on SOW engagements.",
        )
    rec = {
        "engagement_id": eng["id"],
        "name": name,
        "amount_cents": amount,
        "due_date": due,
        "acceptance_status": "PENDING",
        "payment_status": "UNINVOICED",
        "rejection_reason": None,
        "delivered_by_supplier_id": None,
        "accepted_by_user_id": None,
    }
    stamp_new(rec)
    store.milestones[rec["id"]] = rec
    return ok(serializers.milestone(rec), 201)


@bp.get("/v1/engagements/<engagement_id>/milestones")
def list_milestones(engagement_id):
    require_roles(*ALL_READ)
    _get_engagement(engagement_id)
    records = [m for m in store.milestones.values() if m["engagement_id"] == engagement_id]
    page, total, limit, offset = paginate(records, serializers.milestone)
    return ok_list(page, total, limit, offset)


@bp.get("/v1/milestones/<milestone_id>")
def get_milestone(milestone_id):
    require_roles(*ALL_READ)
    return ok(serializers.milestone(_get_milestone(milestone_id)))


@bp.post("/v1/milestones/<milestone_id>/deliver")
def deliver_milestone(milestone_id):
    uid, _ = require_roles("SupplierCoordinator")
    body = get_body()
    opt_str(body, "delivery_note")  # optional; accepted and otherwise ignored
    m = _get_milestone(milestone_id)
    eng = _get_engagement(m["engagement_id"])
    if uid != eng["awarded_supplier_id"]:
        raise_err(ERR_FORBIDDEN, "Only the awarded supplier may deliver this milestone.")
    if m["acceptance_status"] not in ("PENDING", "REJECTED"):
        raise_err(ERR_INVALID_STATE, "Only a PENDING or REJECTED milestone can be delivered.")
    if eng["status"] != "ACTIVE":
        raise_err(ERR_ENGAGEMENT_NOT_ACTIVE, "The engagement is not ACTIVE.")
    sup = store.suppliers.get(eng["awarded_supplier_id"])
    if sup is not None and sup["status"] == "SUSPENDED":
        raise_err(ERR_SUPPLIER_SUSPENDED, "The awarded supplier is suspended.")
    m["acceptance_status"] = "DELIVERED"
    m["delivered_by_supplier_id"] = uid
    m["rejection_reason"] = None
    touch(m)
    if sup is not None:
        sup["milestones_delivered_count"] += 1
        touch(sup)
    return ok(serializers.milestone(m))


@bp.post("/v1/milestones/<milestone_id>/accept")
def accept_milestone(milestone_id):
    uid, _ = require_roles("HiringManager")
    m = _get_milestone(milestone_id)
    if m["acceptance_status"] != "DELIVERED":
        raise_err(ERR_INVALID_STATE, "Only a DELIVERED milestone can be accepted.")
    eng = _get_engagement(m["engagement_id"])
    sup = store.suppliers.get(eng["awarded_supplier_id"] or m["delivered_by_supplier_id"])
    if eng["committed_spend_cents"] + m["amount_cents"] > eng["budget_cents"]:
        raise_err(ERR_BUDGET_EXCEEDED, "Acceptance would exceed the engagement budget.")
    m["acceptance_status"] = "ACCEPTED"
    m["accepted_by_user_id"] = uid
    touch(m)
    if sup is not None:
        sup["milestones_accepted_count"] += 1
        touch(sup)
    run_billable_event(
        eng, sup, m["amount_cents"], "MILESTONE_ACCEPTED", milestone_id=m["id"]
    )
    return ok(serializers.milestone(m))


@bp.post("/v1/milestones/<milestone_id>/reject")
def reject_milestone(milestone_id):
    require_roles("HiringManager")
    body = get_body()
    reason = req_str(body, "reason")
    m = _get_milestone(milestone_id)
    if m["acceptance_status"] != "DELIVERED":
        raise_err(ERR_INVALID_STATE, "Only a DELIVERED milestone can be rejected.")
    m["acceptance_status"] = "REJECTED"
    m["rejection_reason"] = reason
    touch(m)
    return ok(serializers.milestone(m))
