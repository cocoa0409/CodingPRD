"""TitleSearchTask endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from constants import (
    ROLE_DEPARTMENT_DIRECTOR as DD,
    ROLE_RIGHT_OF_WAY_AGENT as RoWA,
    ROLE_TITLE_EXAMINER as TE,
    SEARCH_SCOPES,
)
from errors import raise_err
from middleware import require_roles
from response import success_list, success_object
from services import domain
from services.serializers import serialize_list, serialize_task
from util import (
    apply_filters,
    get_json_body,
    optional_field,
    optional_int,
    paginate,
    parse_pagination,
    require_enum,
    sort_by_created_at,
)

bp = Blueprint("title_searches", __name__)

READERS = (TE, RoWA, DD)


@bp.route("/easement-cases/<case_id>/title-searches", methods=["POST"])
@require_roles(TE)
def create_task(case_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    domain.ensure_case_not_closed(case)
    body = get_json_body()
    search_scope = require_enum(body, "search_scope", SEARCH_SCOPES)

    task = {
        "case_id": case_id,
        "search_scope": search_scope,
        "ordered_by": _user_id,
        "completed_by": None,
        "liens_found": 0,
        "defects_found": 0,
        "chain_of_title_json": None,
        "status": "ORDERED",
    }
    db.stamp_new(task)
    db.title_tasks[task["id"]] = task
    # The latest-task input to title_cleared changed; reconcile the case.
    domain.reconcile_case(case, bump=True)
    return success_object(serialize_task(task), 201)


@bp.route("/easement-cases/<case_id>/title-searches", methods=["GET"])
@require_roles(*READERS)
def list_tasks(case_id: str, _user_id: str, _role: str):
    domain.get_case_or_404(case_id)
    limit, offset = parse_pagination()
    items = [t for t in db.title_tasks.values() if t["case_id"] == case_id]
    items = sort_by_created_at(items)
    items = apply_filters(items, ["status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page, serialize_task), limit, offset, total)


@bp.route("/easement-cases/<case_id>/title-searches/<task_id>", methods=["GET"])
@require_roles(*READERS)
def get_task(case_id: str, task_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    task = domain.get_task_or_404(case, task_id)
    return success_object(serialize_task(task))


@bp.route("/easement-cases/<case_id>/title-searches/<task_id>/begin", methods=["POST"])
@require_roles(TE)
def begin_task(case_id: str, task_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    task = domain.get_task_or_404(case, task_id)
    domain.ensure_case_not_closed(case)
    if task["status"] != "ORDERED":
        raise_err("ERR_INVALID_STATE", "begin requires title search ORDERED")
    task["status"] = "IN_PROGRESS"
    db.touch(task)
    domain.reconcile_case(case, bump=True)
    return success_object(serialize_task(task))


@bp.route("/easement-cases/<case_id>/title-searches/<task_id>/complete", methods=["POST"])
@require_roles(TE)
def complete_task(case_id: str, task_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    task = domain.get_task_or_404(case, task_id)
    domain.ensure_case_not_closed(case)
    if task["status"] != "IN_PROGRESS":
        raise_err("ERR_TASK_NOT_IN_PROGRESS", "TitleSearchTask must be IN_PROGRESS to complete")
    body = get_json_body()
    liens_found = optional_int(body, "liens_found", 0)
    defects_found = optional_int(body, "defects_found", 0)
    chain = optional_field(body, "chain_of_title_json", None)

    # The outcome is derived from the counts. A client may additionally pin an
    # explicit outcome (outcome/status field); declaring COMPLETED_CLEAN while
    # reporting liens or defects is rejected (PRD 3.1).
    explicit = optional_field(body, "outcome", None) or optional_field(body, "status", None)
    if explicit is not None:
        if explicit not in ("COMPLETED_CLEAN", "COMPLETED_WITH_DEFECTS"):
            raise_err("ERR_INVALID_REQUEST", "outcome must be COMPLETED_CLEAN or COMPLETED_WITH_DEFECTS")
        if explicit == "COMPLETED_CLEAN" and (liens_found > 0 or defects_found > 0):
            raise_err("ERR_TITLE_DEFECTS_EXIST", "Cannot complete as clean with liens or defects found")
        if explicit == "COMPLETED_WITH_DEFECTS" and liens_found == 0 and defects_found == 0:
            raise_err("ERR_TITLE_DEFECTS_EXIST", "Cannot complete with defects when none were found")
        outcome = explicit
    else:
        outcome = "COMPLETED_CLEAN" if (liens_found == 0 and defects_found == 0) else "COMPLETED_WITH_DEFECTS"

    task["liens_found"] = liens_found
    task["defects_found"] = defects_found
    task["chain_of_title_json"] = chain
    task["completed_by"] = _user_id
    task["status"] = outcome
    db.touch(task)
    domain.reconcile_case(case, bump=True)
    return success_object(serialize_task(task))


@bp.route("/easement-cases/<case_id>/title-searches/<task_id>/cancel", methods=["POST"])
@require_roles(TE)
def cancel_task(case_id: str, task_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    task = domain.get_task_or_404(case, task_id)
    domain.ensure_case_not_closed(case)
    if task["status"] != "ORDERED":
        raise_err("ERR_INVALID_STATE", "cancel requires title search ORDERED")
    task["status"] = "CANCELLED"
    db.touch(task)
    domain.reconcile_case(case, bump=True)
    return success_object(serialize_task(task))
