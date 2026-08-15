"""Treatment plans and actions (PRD 3.5): budget reservations, owner
execution, bounded extensions, lazy overdue evaluation."""
from flask import Blueprint

from db import store, clock_now
from errors import ApiError
from middleware import authenticate, ALL_ROLES
from response import ok_object, ok_list
from services import (new_entity, touch, serialize_plan, serialize_action,
                      rollup_progress, lazy_plan_sweep, sorted_by_creation)
from util import json_body, req_str, req_dt, paginate

bp = Blueprint("plans", __name__)

PLAN_APPROVE_RISK_STATES = ("ASSESSED", "TREATMENT", "MONITORING", "REASSESSMENT")


def get_plan_or_404(pid):
    p = store["plans"].get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Treatment plan not found")
    return p


def check_plan_owner(plan, uid):
    if plan["owner_user_id"] != uid:
        raise ApiError("ERR_OWNER_MISMATCH", 403,
                       "X-User-ID does not match the plan's owner_user_id")


@bp.get("/treatment-plans/<pid>")
def get_plan(pid):
    authenticate(ALL_ROLES)
    p = get_plan_or_404(pid)
    lazy_plan_sweep(p)  # PRD 2.4: reading a plan re-evaluates overdue slippage
    return ok_object(serialize_plan(p))


@bp.post("/treatment-plans/<pid>/approve")
def approve_plan(pid):
    uid = authenticate(("RiskManager",))
    p = get_plan_or_404(pid)
    if p["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Plan in status %s cannot be approved" % p["status"])
    risk = store["risks"].get(p["risk_id"])
    if risk is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Risk not found")
    # guards in precedence order: risk-state, then SoD, then budget last
    if risk["status"] not in PLAN_APPROVE_RISK_STATES:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Parent risk in status %s cannot accept plan approval"
                       % risk["status"])
    if uid == p["proposer_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 422,
                       "Approver must differ from the plan's proposer")
    available = risk["treatment_budget_cents"] - risk["reserved_treatment_cents"]
    if available < p["budget_cents"]:
        raise ApiError("ERR_BUDGET_EXCEEDED", 422,
                       "Plan budget exceeds the risk's available treatment budget")
    p["status"] = "APPROVED"
    touch(p)
    risk["reserved_treatment_cents"] += p["budget_cents"]
    touch(risk)
    return ok_object(serialize_plan(p))


@bp.post("/treatment-plans/<pid>/reject")
def reject_plan(pid):
    uid = authenticate(("RiskManager",))
    json_body()  # optional reason; not persisted
    p = get_plan_or_404(pid)
    if p["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Plan in status %s cannot be rejected" % p["status"])
    if uid == p["proposer_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 422,
                       "Rejector must differ from the plan's proposer")
    p["status"] = "REJECTED"
    touch(p)
    return ok_object(serialize_plan(p))


@bp.post("/treatment-plans/<pid>/start")
def start_plan(pid):
    uid = authenticate(("RiskOwner",))
    p = get_plan_or_404(pid)
    check_plan_owner(p, uid)
    if p["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Plan in status %s cannot be started" % p["status"])
    p["status"] = "IN_PROGRESS"
    touch(p)
    return ok_object(serialize_plan(p))


@bp.post("/treatment-plans/<pid>/complete")
def complete_plan(pid):
    uid = authenticate(("RiskOwner",))
    p = get_plan_or_404(pid)
    check_plan_owner(p, uid)
    if p["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Plan in status %s cannot be completed" % p["status"])
    acts = [a for a in store["actions"].values() if a["plan_id"] == p["id"]]
    if not acts or any(a["status"] != "DONE" for a in acts):
        raise ApiError("ERR_INCOMPLETE_ACTIONS", 409,
                       "Completion requires at least one action and all actions DONE")
    p["status"] = "COMPLETED"
    touch(p)
    risk = store["risks"].get(p["risk_id"])
    if risk is not None:
        risk["reserved_treatment_cents"] -= p["budget_cents"]
        touch(risk)
    return ok_object(serialize_plan(p))


@bp.post("/treatment-plans/<pid>/cancel")
def cancel_plan(pid):
    uid = authenticate(("RiskOwner",))
    json_body()  # optional reason; not persisted
    p = get_plan_or_404(pid)
    check_plan_owner(p, uid)
    if p["status"] not in ("APPROVED", "IN_PROGRESS", "OVERDUE"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Plan in status %s cannot be cancelled" % p["status"])
    p["status"] = "CANCELLED"
    touch(p)
    risk = store["risks"].get(p["risk_id"])
    if risk is not None:
        risk["reserved_treatment_cents"] -= p["budget_cents"]
        touch(risk)
    return ok_object(serialize_plan(p))


@bp.post("/treatment-plans/<pid>/extend")
def extend_plan(pid):
    uid = authenticate(("RiskOwner",))
    data = json_body()
    new_due = req_dt(data, "new_due_date")
    p = get_plan_or_404(pid)
    check_plan_owner(p, uid)
    if p["status"] != "OVERDUE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an OVERDUE plan can be extended")
    if p["extension_count"] >= 3:
        raise ApiError("ERR_PLAN_EXTENSION_LIMIT", 409,
                       "At most three extensions are permitted")
    if not new_due > clock_now():
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "new_due_date must be after the current logical clock")
    p["due_date"] = new_due
    p["extension_count"] += 1
    p["status"] = "IN_PROGRESS"
    touch(p)
    return ok_object(serialize_plan(p))


@bp.post("/treatment-plans/<pid>/actions")
def create_action(pid):
    uid = authenticate(("RiskOwner",))
    data = json_body()
    title = req_str(data, "title")
    p = get_plan_or_404(pid)
    check_plan_owner(p, uid)
    if p["status"] not in ("APPROVED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Actions can be added only while the plan is APPROVED or IN_PROGRESS")
    a = new_entity()
    a.update({"plan_id": p["id"], "title": title, "status": "PENDING"})
    store["actions"][a["id"]] = a
    rollup_progress(p)
    return ok_object(serialize_action(a), 201)


@bp.get("/treatment-plans/<pid>/actions")
def list_actions(pid):
    authenticate(ALL_ROLES)
    get_plan_or_404(pid)
    items = sorted_by_creation(
        a for a in store["actions"].values() if a["plan_id"] == pid)
    page, meta = paginate(items)
    return ok_list([serialize_action(a) for a in page], meta)
