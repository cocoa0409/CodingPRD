"""Delivery milestones (PRD §3.5): uniqueness per plan, completion may bubble
an APPROVED plan up to DELIVERED.
"""
from flask import Blueprint

from db import store, new_entity, public, touch
from errors import ApiError, ERR_INVALID_STATE, ERR_DUPLICATE_MILESTONE
from middleware import (
    authenticate, body, require_fields, check_enums, get_fk, get_path,
    MILESTONE_TYPES, ALL_ROLES,
)
from response import success_object
from routes import list_response
from services import cascades

bp = Blueprint("milestones", __name__)


@bp.post("/api/delivery-milestones")
def create_milestone():
    authenticate(["ProjectManager"])
    b = body()
    plan = get_fk(b, "plan_id", store.plans)
    require_fields(b, [
        ("plan_id", "string", True),
        ("milestone_type", "string", True),
        ("planned_date", "datetime", True),
    ])
    if plan is None:
        plan = store.plans[b["plan_id"]]
    check_enums(b, [("milestone_type", MILESTONE_TYPES)])
    # Priority 14/19: wrong plan status or a repeated type are rejected alike.
    if plan["status"] not in ("SCHEMATIC", "PRICED", "APPROVED"):
        raise ApiError(ERR_DUPLICATE_MILESTONE,
                       f"Cannot add a milestone to a plan in status {plan['status']}", 409)
    dupe = any(m["plan_id"] == plan["id"] and m["milestone_type"] == b["milestone_type"]
               for m in store.milestones.values())
    if dupe:
        raise ApiError(ERR_DUPLICATE_MILESTONE,
                       "milestone_type already used on this plan", 409)
    ent = new_entity({
        "plan_id": plan["id"],
        "milestone_type": b["milestone_type"],
        "planned_date": b["planned_date"],
        "actual_date": None,
        "status": "PENDING",
    })
    store.milestones[ent["id"]] = ent
    return success_object(public(ent), 201)


@bp.get("/api/delivery-milestones")
def list_milestones():
    authenticate(ALL_ROLES)
    return list_response(store.milestones.values(), [
        ("plan_id", lambda e: e["plan_id"]),
        ("milestone_type", lambda e: e["milestone_type"]),
        ("status", lambda e: e["status"]),
    ])


@bp.get("/api/delivery-milestones/<mid>")
def get_milestone(mid):
    authenticate(ALL_ROLES)
    return success_object(public(get_path(store.milestones, mid, "delivery milestone")))


@bp.post("/api/delivery-milestones/<mid>/complete")
def complete_milestone(mid):
    authenticate(["ProjectManager"])
    ms = get_path(store.milestones, mid, "delivery milestone")
    b = body()
    require_fields(b, [("actual_date", "datetime", True)])
    if ms["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot complete a milestone in status {ms['status']}", 409)
    plan = store.plans[ms["plan_id"]]
    if plan["status"] not in ("SCHEMATIC", "PRICED", "APPROVED"):
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot complete a milestone while the plan is {plan['status']}", 409)
    ms["actual_date"] = b["actual_date"]
    ms["status"] = "COMPLETE"
    touch(ms)
    # Bubble-up: completing the last PENDING milestone of an APPROVED plan
    # transitions the plan APPROVED -> DELIVERED with its cascades.
    if plan["status"] == "APPROVED" and cascades.all_milestones_complete(plan["id"]):
        cascades.deliver_plan_cascade(plan)
    return success_object(public(ms))
