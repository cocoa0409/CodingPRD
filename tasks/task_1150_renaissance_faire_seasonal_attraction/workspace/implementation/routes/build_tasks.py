"""BuildTask endpoints."""
from flask import Blueprint, request

from db import store, new_id, next_seq
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_TASK_NOT_FOUND,
    ERR_SEASON_NOT_FOUND,
    ERR_SEASON_INVALID_STATE,
    ERR_TASK_DEPENDENCY_CYCLE,
    ERR_TASK_DEPENDENCY_UNMET,
    ERR_TASK_NOT_ADVANCEABLE,
    conflict,
)
from middleware import (
    require_roles,
    get_body,
    load,
    parse_pagination,
    apply_filters,
    sorted_by_creation,
)
from response import obj_response, list_response
from services import rederive_posture, task_reaches
from util import req, opt, check_unknown, new_record, mutate, public_view

bp = Blueprint("build_tasks", __name__)

PHASES = {"BUILD", "STRIKE"}
ADVANCE_TARGETS = {"IN_PROGRESS", "DONE"}
CREATE_FIELDS = {"season_id", "phase", "name", "depends_on_task_ids"}

BUILD_PHASE_SEASON_STATES = {"PLANNING", "BUILD"}
STRIKE_PHASE_SEASON_STATES = {"PLANNING", "BUILD", "OPEN", "STRIKE"}


def load_task(tid):
    return load(store.tasks, tid, ERR_TASK_NOT_FOUND, "build task")


def _check_deps_exist_and_same_season(dep_ids, season_id):
    for dep_id in dep_ids:
        dep = load(store.tasks, dep_id, ERR_TASK_NOT_FOUND, "build task")
        if dep["season_id"] != season_id:
            raise ApiError(
                ERR_INVALID_REQUEST, 400, "dependencies must reference tasks of the same season"
            )


def _check_no_cycle(task_id, dep_ids):
    for dep_id in dep_ids:
        if dep_id == task_id or task_reaches(dep_id, task_id):
            raise conflict(
                ERR_TASK_DEPENDENCY_CYCLE,
                "depends_on_task_ids would create a dependency cycle within the season",
            )


@bp.route("/build-tasks", methods=["POST"])
def create_task():
    require_roles("FaireOperator")
    body = get_body()
    if isinstance(body.get("season_id"), str):
        load(store.seasons, body["season_id"], ERR_SEASON_NOT_FOUND, "season")
    check_unknown(body, CREATE_FIELDS)
    season_id = req(body, "season_id", "str")
    phase = req(body, "phase", "enum", enum=PHASES)
    name = req(body, "name", "str")
    dep_ids = opt(body, "depends_on_task_ids", "list_str") or []
    _check_deps_exist_and_same_season(dep_ids, season_id)

    season = store.seasons[season_id]
    allowed = (
        BUILD_PHASE_SEASON_STATES if phase == "BUILD" else STRIKE_PHASE_SEASON_STATES
    )
    if season["status"] not in allowed:
        raise conflict(
            ERR_SEASON_INVALID_STATE,
            "%s-phase task creation is not allowed in season state %s"
            % (phase, season["status"]),
        )
    task = new_record()
    task.update(
        {
            "id": new_id(),
            "_seq": next_seq(),
            "season_id": season_id,
            "phase": phase,
            "name": name,
            "status": "PENDING",
            "depends_on_task_ids": list(dict.fromkeys(dep_ids)),
        }
    )
    store.tasks[task["id"]] = task
    # A PENDING BUILD-phase task blocks readiness.
    rederive_posture(season)
    return obj_response(public_view(task), 201)


@bp.route("/build-tasks", methods=["GET"])
def list_tasks():
    require_roles()
    limit, offset = parse_pagination()
    items = apply_filters(
        sorted_by_creation(store.tasks),
        [("season_id", "season_id"), ("phase", "phase"), ("status", "status")],
    )
    dep_filter = request.args.get("depends_on_task_ids")
    if dep_filter is not None:
        items = [t for t in items if dep_filter in t["depends_on_task_ids"]]
    total = len(items)
    page = items[offset : offset + limit]
    return list_response([public_view(t) for t in page], limit, offset, total)


@bp.route("/build-tasks/<tid>", methods=["GET"])
def get_task(tid):
    require_roles()
    return obj_response(public_view(load_task(tid)))


@bp.route("/build-tasks/<tid>/dependents", methods=["GET"])
def list_dependents(tid):
    require_roles()
    task = load_task(tid)
    limit, offset = parse_pagination()
    items = [
        t
        for t in sorted_by_creation(store.tasks)
        if task["id"] in t["depends_on_task_ids"]
    ]
    total = len(items)
    page = items[offset : offset + limit]
    return list_response([public_view(t) for t in page], limit, offset, total)


@bp.route("/build-tasks/<tid>/dependencies", methods=["POST"])
def add_dependencies(tid):
    require_roles("FaireOperator")
    task = load_task(tid)
    body = get_body()
    check_unknown(body, {"add_task_ids"})
    add_ids = req(body, "add_task_ids", "list_str")
    if task["status"] == "DONE":
        raise conflict(
            ERR_TASK_NOT_ADVANCEABLE, "dependencies can only be added to a non-terminal task"
        )
    for dep_id in add_ids:
        dep = load(store.tasks, dep_id, ERR_TASK_NOT_FOUND, "build task")
        if dep["season_id"] != task["season_id"]:
            raise ApiError(
                ERR_INVALID_REQUEST, 400, "dependencies must reference tasks of the same season"
            )
        if dep["status"] == "DONE":
            raise ApiError(
                ERR_INVALID_REQUEST, 400, "cannot add a dependency on a terminal task"
            )
    new_ids = [d for d in add_ids if d not in task["depends_on_task_ids"]]
    _check_no_cycle(task["id"], task["depends_on_task_ids"] + new_ids)
    mutate(task, depends_on_task_ids=task["depends_on_task_ids"] + new_ids)
    return obj_response(public_view(task))


@bp.route("/build-tasks/<tid>/advance", methods=["POST"])
def advance_task(tid):
    require_roles("FaireOperator")
    task = load_task(tid)
    body = get_body()
    check_unknown(body, {"to"})
    to = req(body, "to", "enum", enum=ADVANCE_TARGETS)
    if to == "IN_PROGRESS":
        if task["status"] != "PENDING":
            raise conflict(
                ERR_TASK_NOT_ADVANCEABLE, "advance to IN_PROGRESS requires PENDING"
            )
        unmet = any(
            store.tasks[dep_id]["status"] != "DONE"
            for dep_id in task["depends_on_task_ids"]
            if dep_id in store.tasks
        )
        if unmet:
            raise conflict(
                ERR_TASK_DEPENDENCY_UNMET,
                "advance to IN_PROGRESS requires all depends_on_task_ids DONE",
            )
        mutate(task, status="IN_PROGRESS")
    else:  # DONE
        if task["status"] != "IN_PROGRESS":
            raise conflict(ERR_TASK_NOT_ADVANCEABLE, "advance to DONE requires IN_PROGRESS")
        mutate(task, status="DONE")
        if task["phase"] == "BUILD":
            season = store.seasons.get(task["season_id"])
            if season is not None:
                rederive_posture(season)
    return obj_response(public_view(task))
