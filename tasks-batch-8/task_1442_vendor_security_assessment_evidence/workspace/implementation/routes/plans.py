"""RemediationPlan lifecycle (PRD §3.6): PROPOSED -> ACCEPTED -> IN_PROGRESS
-> COMPLETED -> VERIFIED / REJECTED, with the acceptor/verifier segregation
of duties and the exception cascades on both verification exits.
"""
from flask import Blueprint, g

import db
import errors
import helpers
import util
from errors import ApiError
from middleware import body, require_roles, scope_vendor_or_403
from response import ok
from serializers import serialize

bp = Blueprint("plans", __name__,
               url_prefix="/vsa/vendors/<vid>/cycles/<cid>/remediation-plans")


def _resolve(vid, cid):
    vendor = helpers.get_vendor(vid)
    scope_vendor_or_403(vid)
    cycle = helpers.get_cycle_for_vendor(vendor, cid)
    return vendor, cycle


def _get_plan(cycle, pid):
    return helpers.get_child(db.plans, "cycle_id", cycle, pid, "RemediationPlan")


def _validate_tasks(tasks):
    if not isinstance(tasks, list) or not tasks:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "tasks must be a non-empty list")
    for task in tasks:
        if not isinstance(task, dict):
            raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                           "each task must be an object")
        for field in ("task_key", "description", "due_at", "owner"):
            if field not in task:
                raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                               "task is missing %s" % field)
        if not isinstance(task["task_key"], str) or not task["task_key"]:
            raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                           "task_key must be a non-empty string")


@bp.post("")
@require_roles("RiskAnalyst")
def create_plan(vid, cid):
    vendor, cycle = _resolve(vid, cid)
    data = body()
    exception_ids = data.get("exception_ids")
    tasks = data.get("tasks")
    if not isinstance(exception_ids, list) or not exception_ids:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "exception_ids must be a non-empty list")
    if tasks is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "tasks is required")
    _validate_tasks(tasks)
    # Referential integrity (priority 10): every exception belongs to this
    # cycle and is currently OPEN.
    for eid in exception_ids:
        exc = db.exceptions.get(eid)
        if exc is None or exc["cycle_id"] != cid or exc["status"] != "OPEN":
            raise ApiError(errors.ERR_REFERENTIAL_INTEGRITY, 422,
                           "Every referenced exception must belong to the "
                           "cycle and be OPEN")
    plan = {
        "cycle_id": cid,
        "exception_ids": list(exception_ids),
        "tasks": tasks,
        "status": "PROPOSED",
        "approved_by": None,
        "completed_task_keys": [],
        "verified_at": None,
    }
    helpers.stamp_new("plans", plan)
    db.plans[plan["id"]] = plan
    return ok(serialize("plan", plan), 201)


@bp.post("/<pid>/accept")
@require_roles("RiskAnalyst")
def accept_plan(vid, cid, pid):
    vendor, cycle = _resolve(vid, cid)
    plan = _get_plan(cycle, pid)
    if plan["status"] != "PROPOSED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a PROPOSED plan can be accepted")
    if cycle["status"] != "REMEDIATION":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Cycle is not in REMEDIATION")
    for eid in plan["exception_ids"]:
        exc = db.exceptions.get(eid)
        if exc is None or exc["status"] != "OPEN":
            raise ApiError(errors.ERR_REFERENTIAL_INTEGRITY, 422,
                           "Every linked exception must still be OPEN")
    plan["status"] = "ACCEPTED"
    plan["approved_by"] = g.user_id
    for eid in plan["exception_ids"]:
        exc = db.exceptions[eid]
        exc["status"] = "IN_REMEDIATION"
        helpers.touch("exceptions", exc)
    helpers.touch("plans", plan)
    return ok(serialize("plan", plan))


@bp.post("/<pid>/reject")
@require_roles("RiskAnalyst")
def reject_plan(vid, cid, pid):
    vendor, cycle = _resolve(vid, cid)
    plan = _get_plan(cycle, pid)
    if plan["status"] != "PROPOSED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a PROPOSED plan can be rejected")
    plan["status"] = "REJECTED"
    helpers.touch("plans", plan)
    return ok(serialize("plan", plan))


@bp.post("/<pid>/progress")
@require_roles("VendorContact")
def progress_plan(vid, cid, pid):
    vendor, cycle = _resolve(vid, cid)
    plan = _get_plan(cycle, pid)
    if plan["status"] not in ("ACCEPTED", "IN_PROGRESS"):
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only an ACCEPTED or IN_PROGRESS plan accepts progress")
    data = body()
    completed = data.get("completed_task_keys")
    if not isinstance(completed, list) or not completed:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "completed_task_keys must be a non-empty list")
    task_keys = {t["task_key"] for t in plan["tasks"]}
    if any(not isinstance(k, str) for k in completed) \
            or not set(completed) <= task_keys:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "completed_task_keys must be a subset of the plan's task keys")
    merged = sorted(set(plan.get("completed_task_keys", [])) | set(completed))
    plan["completed_task_keys"] = merged
    if set(merged) == task_keys:
        plan["status"] = "COMPLETED"
    elif plan["status"] == "ACCEPTED":
        plan["status"] = "IN_PROGRESS"
    helpers.touch("plans", plan)
    return ok(serialize("plan", plan))


@bp.post("/<pid>/verify")
@require_roles("RiskAnalyst")
def verify_plan(vid, cid, pid):
    vendor, cycle = _resolve(vid, cid)
    plan = _get_plan(cycle, pid)
    if plan["status"] != "COMPLETED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a COMPLETED plan can be verified")
    # Segregation of duties: verifier differs from the accepting analyst.
    if g.user_id == plan.get("approved_by"):
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 422,
                       "Plan verifier must differ from the plan acceptor")
    data = body()
    rejecting = data.get("reject", False) is True
    if not rejecting:
        task_keys = {t["task_key"] for t in plan["tasks"]}
        if set(plan.get("completed_task_keys", [])) != task_keys:
            raise ApiError(errors.ERR_PLAN_TASKS_INCOMPLETE, 422,
                           "completed_task_keys must equal the full task key set")
        plan["status"] = "VERIFIED"
        plan["verified_at"] = util.iso(util.now())
        closure = data.get("closure_reason") or data.get("note") \
            or "REMEDIATION_VERIFIED"
        closed = 0
        for eid in plan["exception_ids"]:
            exc = db.exceptions.get(eid)
            if exc is not None and exc["status"] == "IN_REMEDIATION":
                exc["status"] = "CLOSED_REMEDIATED"
                exc["closure_reason"] = closure
                helpers.touch("exceptions", exc)
                closed += 1
        cycle["open_exception_count"] -= closed
        helpers.touch("cycles", cycle)
    else:
        # Failed verification: compensate by returning exceptions to OPEN;
        # open_exception_count is unchanged (they were open all along).
        plan["status"] = "REJECTED"
        for eid in plan["exception_ids"]:
            exc = db.exceptions.get(eid)
            if exc is not None and exc["status"] == "IN_REMEDIATION":
                exc["status"] = "OPEN"
                helpers.touch("exceptions", exc)
        helpers.touch("cycles", cycle)
    helpers.touch("plans", plan)
    return ok(serialize("plan", plan))
