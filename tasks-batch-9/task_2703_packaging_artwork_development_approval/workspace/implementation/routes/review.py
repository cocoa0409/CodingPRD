"""PRD 3.5 - routing passes, review tasks and the approval cascade."""
from flask import Blueprint, request

import calc
from cascade import approve_version, reject_version
from core import db, now_iso, rows, touch
from errors import fail, invalid
from http_util import (
    ALL_ROLES,
    auth,
    body_fields,
    filter_exists,
    load,
    need_enum,
    ok,
    paginate,
    query_int,
)
from serialize import route_json, task_json

bp = Blueprint("review", __name__)

REVIEWER_ROLES = ["BrandReviewer", "LegalReviewer", "RegulatoryReviewer", "QualityReviewer"]


def _route_tasks(route_id):
    return [t for t in rows("tasks") if t["review_route_id"] == route_id]


@bp.route("/review-routes/<route_id>", methods=["GET"])
def get_route(route_id):
    auth(ALL_ROLES)
    return ok(route_json(load("routes", route_id)))


@bp.route("/review-routes", methods=["GET"])
def list_routes():
    auth(ALL_ROLES)
    version_id = filter_exists("versions", "artwork_version_id")
    items = rows("routes")
    if version_id:
        items = [r for r in items if r["artwork_version_id"] == version_id]
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    items = sorted(items, key=lambda r: (r["route_no"], r["created_at"], r["_seq"]))
    return paginate(items, route_json)


@bp.route("/review-tasks/<task_id>", methods=["GET"])
def get_task(task_id):
    auth(ALL_ROLES)
    return ok(task_json(load("tasks", task_id)))


@bp.route("/review-tasks", methods=["GET"])
def list_tasks():
    auth(ALL_ROLES)
    route_id = filter_exists("routes", "review_route_id")
    items = rows("tasks")
    if route_id:
        items = [t for t in items if t["review_route_id"] == route_id]
    discipline = request.args.get("discipline")
    if discipline:
        items = [t for t in items if t["discipline"] == discipline]
    stage_no = query_int("stage_no")
    if stage_no is not None:
        items = [t for t in items if t["stage_no"] == stage_no]
    decision = request.args.get("decision")
    if decision:
        items = [t for t in items if t["decision"] == decision]
    items = sorted(items, key=lambda t: (t["stage_no"], t["created_at"], t["_seq"]))
    return paginate(items, task_json)


def _resolve_stage(route, stage_no):
    """PRD 3.5: only the tasks of the stage being resolved are considered."""
    stage_tasks = [t for t in _route_tasks(route["id"]) if t["stage_no"] == stage_no]
    for task in stage_tasks:
        if task["decision"] == "REJECTED":
            return "REJECTED"
    for task in stage_tasks:
        if task["decision"] not in calc.APPROVING_DECISIONS:
            return None
    return "APPROVED"


def _activate_stage(route, stage_no):
    for task in _route_tasks(route["id"]):
        if task["stage_no"] == stage_no:
            task["is_active"] = True
            touch(task)


def _skip_pending(route):
    for task in _route_tasks(route["id"]):
        if task["decision"] == "PENDING":
            task["decision"] = "SKIPPED"
            task["is_active"] = False
            touch(task)


@bp.route("/review-tasks/<task_id>/decision", methods=["POST"])
def decide_task(task_id):
    user_id, role = auth(REVIEWER_ROLES)
    task = load("tasks", task_id)
    route = db.routes[task["review_route_id"]]
    version = db.versions[task["artwork_version_id"]]

    # Band 1: the finer-grained discipline binding also answers ERR_UNAUTHORIZED (PRD 2.1).
    if calc.DISCIPLINE_ROLE[task["discipline"]] != role:
        fail(
            "ERR_UNAUTHORIZED",
            "a %s task requires the %s role"
            % (task["discipline"], calc.DISCIPLINE_ROLE[task["discipline"]]),
        )

    # Band 3: segregation of duties (PRD 2.1, 2.7).
    if user_id == version["author_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the version author may not decide its review tasks")
    for sibling in _route_tasks(route["id"]):
        if sibling["id"] == task["id"]:
            continue
        if sibling.get("decided_by_user_id") == user_id:
            fail(
                "ERR_SEGREGATION_OF_DUTIES",
                "this user already decided another task on the same routing pass",
            )

    body = body_fields(["decision"], ["comment", "condition_code"])
    decision = need_enum(body, "decision", ("APPROVED", "REJECTED", "CONDITIONAL"))
    comment = body.get("comment")
    condition_code = body.get("condition_code")
    if comment is not None and not isinstance(comment, str):
        invalid("comment must be a string")
    if condition_code is not None and not isinstance(condition_code, str):
        invalid("condition_code must be a string")
    if decision == "REJECTED" and (comment is None or not comment.strip()):
        invalid("a REJECTED decision requires a non-empty comment")
    if decision == "CONDITIONAL" and (condition_code is None or not condition_code.strip()):
        invalid("a CONDITIONAL decision requires a non-empty condition_code")

    # Band 6: the stage check is reported ahead of the already-decided check (PRD 3.5).
    if (
        not task["is_active"]
        or task["stage_no"] != route["current_stage_no"]
        or route["status"] != "IN_PROGRESS"
    ):
        fail("ERR_ROUTE_STAGE_NOT_ACTIVE", "the task's stage is not the active stage of the pass")
    if task["decision"] != "PENDING":
        fail("ERR_TASK_ALREADY_DECIDED", "the task has already been decided")

    stamp = now_iso()
    task["decision"] = decision
    task["decided_by_user_id"] = user_id
    task["decided_at"] = stamp
    if decision == "REJECTED":
        task["comment"] = comment
    elif decision == "APPROVED":
        task["comment"] = comment
    else:
        task["comment"] = comment
        task["condition_code"] = condition_code
        version["open_condition_codes"] = list(version["open_condition_codes"]) + [condition_code]
    touch(task)

    route["conditional_count"] = len(
        [t for t in _route_tasks(route["id"]) if t["decision"] == "CONDITIONAL"]
    )

    stage_no = task["stage_no"]
    verdict = _resolve_stage(route, stage_no)
    if verdict == "REJECTED":
        route["status"] = "COMPLETE_REJECTED"
        route["completed_at"] = stamp
        touch(route)
        _skip_pending(route)
        reject_version(version)
    elif verdict == "APPROVED":
        if route["current_stage_no"] < calc.FINAL_STAGE_NO:
            route["current_stage_no"] = route["current_stage_no"] + 1
            touch(route)
            _activate_stage(route, route["current_stage_no"])
        else:
            route["status"] = "COMPLETE_APPROVED"
            route["completed_at"] = stamp
            touch(route)
            approve_version(version, route)
    else:
        touch(route)
        if decision == "CONDITIONAL":
            touch(version)

    return ok(task_json(task))
