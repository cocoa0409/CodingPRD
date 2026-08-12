from flask import Blueprint, request

from db import STORE, mark, sort_created
from errors import (ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE_TRANSITION,
                    ERR_NOT_TASK_OWNER, ERR_SOD_VIOLATION)
from response import ok_object, ok_list
import serializers as ser
from validate import require_roles, body, req_enum, opt_str, pagination

bp = Blueprint("review_tasks", __name__)

ALL_READ = ("RevenueAccountant", "RevenueManager", "ContractReviewer", "Controller")


def get_task_or_404(task_id):
    t = STORE.review_tasks.get(task_id)
    if t is None:
        raise ApiError(ERR_NOT_FOUND, 404, "task_id does not identify an existing review task")
    return t


@bp.get("/revrec/review-tasks")
def list_tasks():
    require_roles(*ALL_READ)
    limit, offset = pagination()
    items = list(STORE.review_tasks.values())
    for f in ("contract_id", "clause_id", "status", "reviewer_user_id"):
        v = request.args.get(f)
        if v is not None:
            items = [t for t in items if str(t.get(f)) == v]
    items = sort_created(items)
    total = len(items)
    return ok_list([ser.review_task(t) for t in items[offset:offset + limit]], limit, offset, total)


@bp.get("/revrec/review-tasks/<task_id>")
def get_task(task_id):
    require_roles(*ALL_READ)
    return ok_object(ser.review_task(get_task_or_404(task_id)))


@bp.post("/revrec/review-tasks/<task_id>/start")
def start_task(task_id):
    uid = require_roles("ContractReviewer")
    t = get_task_or_404(task_id)
    if t["status"] != "ASSIGNED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "start requires the task to be ASSIGNED")
    t["status"] = "IN_REVIEW"
    t["reviewer_user_id"] = uid
    mark(t)
    return ok_object(ser.review_task(t))


@bp.post("/revrec/review-tasks/<task_id>/recommend")
def recommend_task(task_id):
    uid = require_roles("ContractReviewer")
    t = get_task_or_404(task_id)
    # Task ownership is enforced at the authorization tier.
    if t["reviewer_user_id"] != uid:
        raise ApiError(ERR_NOT_TASK_OWNER, 403, "recommend requires the claiming reviewer")
    data = body()
    recommendation = req_enum(data, "recommendation", {"APPROVE", "REJECT"})
    note = opt_str(data, "note")
    if t["status"] != "IN_REVIEW":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "recommend requires the task to be IN_REVIEW")
    t["status"] = "RECOMMENDED"
    t["recommendation"] = recommendation
    t["recommended_by_user_id"] = uid
    if note is not None:
        t["note"] = note
    mark(t)
    return ok_object(ser.review_task(t))


@bp.post("/revrec/review-tasks/<task_id>/decide")
def decide_task(task_id):
    uid = require_roles("ContractReviewer")
    t = get_task_or_404(task_id)
    data = body()
    decision = req_enum(data, "decision", {"APPROVED", "REJECTED", "RETURN"})
    note = opt_str(data, "note")
    if t["status"] != "RECOMMENDED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "decide requires the task to be RECOMMENDED")
    if uid == t["recommended_by_user_id"]:
        raise ApiError(ERR_SOD_VIOLATION, 409, "the decider must differ from the recommender")
    t["decision"] = decision
    t["decided_by_user_id"] = uid
    if note is not None:
        t["note"] = note
    if decision == "RETURN":
        # Rework loop: back to IN_REVIEW; recommendation cleared; reviewer kept.
        t["status"] = "IN_REVIEW"
        t["recommendation"] = None
        t["recommended_by_user_id"] = None
    else:
        t["status"] = "DECIDED"
        cl = STORE.clauses.get(t["clause_id"])
        if cl is not None:
            cl["status"] = decision  # APPROVED or REJECTED
            mark(cl)
    mark(t)
    return ok_object(ser.review_task(t))
