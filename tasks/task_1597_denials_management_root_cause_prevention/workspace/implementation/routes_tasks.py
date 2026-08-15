"""Routes: root-cause tasks (manual create, acknowledge, implement-fix,
verify, close)."""

from datetime import timedelta

from flask import Blueprint, g, request

from auth import require_roles
from db import store
from envelope import list_response, ok
from errors import (
    ApiError,
    ERR_INVALID_RECURRENCE_LINK,
    ERR_MONITORING_WINDOW_ACTIVE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_TASK_INVALID_STATE,
)
from services import (
    MONITORING_DAYS,
    bump_scorecard,
    emit_event,
    find_denial,
    find_task,
    make_record,
    matching_scorecard,
    public,
    touch,
)
from util import (
    ALL_ROLES,
    TASK_TYPES,
    get_body,
    now_iso,
    opt_str,
    parse_date,
    req_date,
    req_enum,
    req_str,
    sort_created,
    today,
)

bp = Blueprint("tasks", __name__)


@bp.post("/rcm/root-cause-tasks")
@require_roles("DenialsManager")
def create_task():
    body = get_body()
    denial_id = req_str(body, "denial_case_id")
    task_type = req_enum(body, "task_type", TASK_TYPES)
    description = req_str(body, "description")
    due_date = req_date(body, "due_date")
    recurrence_id = opt_str(body, "recurrence_of_task_id")

    denial = find_denial(denial_id)
    department = denial.get("root_cause_department")
    if recurrence_id is not None:
        prior = find_task(recurrence_id)  # ERR_NOT_FOUND when unresolvable
        if (
            prior["status"] != "VERIFIED"
            or prior["department"] != department
        ):
            raise ApiError(
                ERR_INVALID_RECURRENCE_LINK,
                422,
                "recurrence_of_task_id must reference a VERIFIED task in the "
                "same department",
            )
    task = make_record(
        {
            "denial_case_id": denial_id,
            "department": department,
            "task_type": task_type,
            "description": description,
            "due_date": due_date,
            "status": "OPEN",
            "implemented_by_user_id": None,
            "fix_summary": "",
            "verified_at": None,
            "monitoring_until_date": None,
            "recurrence_of_task_id": recurrence_id,
            "reopened_count": 0,
        }
    )
    store.tasks[task["id"]] = task
    sc = matching_scorecard(department, today())
    if sc is not None:
        bump_scorecard(sc, open_task_count=1)
    emit_event(
        denial_id,
        "TASK_CREATED",
        g.user_role,
        g.user_id,
        "task_id=%s;department=%s;task_type=%s" % (task["id"], department, task_type),
    )
    return ok(public(task), "object", 201)


@bp.get("/rcm/root-cause-tasks")
@require_roles(*ALL_ROLES)
def list_tasks():
    items = list(store.tasks.values())
    for param, field in (
        ("denial_case_id", "denial_case_id"),
        ("department", "department"),
        ("status", "status"),
        ("recurrence_of_task_id", "recurrence_of_task_id"),
    ):
        val = request.args.get(param)
        if val is not None:
            items = [t for t in items if t[field] == val]
    return list_response([public(t) for t in sort_created(items)])


@bp.get("/rcm/root-cause-tasks/<tid>")
@require_roles(*ALL_ROLES)
def get_task(tid):
    return ok(public(find_task(tid)))


@bp.post("/rcm/root-cause-tasks/<tid>/acknowledge")
@require_roles("UpstreamOwner")
def acknowledge_task(tid):
    task = find_task(tid)
    if task["status"] not in ("OPEN", "REOPENED"):
        raise ApiError(
            ERR_TASK_INVALID_STATE,
            409,
            "Acknowledge requires OPEN or REOPENED status",
        )
    task["status"] = "ACKNOWLEDGED"
    touch(task)
    return ok(public(task))


@bp.post("/rcm/root-cause-tasks/<tid>/implement-fix")
@require_roles("UpstreamOwner")
def implement_fix(tid):
    body = get_body()
    fix_summary = req_str(body, "fix_summary")
    task = find_task(tid)
    if task["status"] != "ACKNOWLEDGED":
        raise ApiError(
            ERR_TASK_INVALID_STATE, 409, "Implement-fix requires ACKNOWLEDGED status"
        )
    task["implemented_by_user_id"] = g.user_id
    task["fix_summary"] = fix_summary
    task["status"] = "FIX_IMPLEMENTED"
    touch(task)
    return ok(public(task))


@bp.post("/rcm/root-cause-tasks/<tid>/verify")
@require_roles("DenialsManager")
def verify_task(tid):
    task = find_task(tid)
    if task["status"] != "FIX_IMPLEMENTED":
        raise ApiError(
            ERR_TASK_INVALID_STATE, 409, "Verify requires FIX_IMPLEMENTED status"
        )
    if g.user_id == task["implemented_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            403,
            "Verifier must differ from the implementer",
        )
    today_d = today()
    task["verified_at"] = now_iso()
    task["monitoring_until_date"] = (
        today_d + timedelta(days=MONITORING_DAYS)
    ).isoformat()
    task["status"] = "VERIFIED"
    touch(task)
    sc = matching_scorecard(task["department"], today_d)
    if sc is not None:
        denial = store.denials.get(task["denial_case_id"])
        linked = denial["denied_amount_cents"] if denial else 0
        bump_scorecard(
            sc,
            verified_fix_count=1,
            verified_linked_denied_cents=linked,
            open_task_count=-1,
        )
    emit_event(
        task["denial_case_id"],
        "TASK_VERIFIED",
        g.user_role,
        g.user_id,
        "task_id=%s;verified_at=%s" % (task["id"], task["verified_at"]),
    )
    return ok(public(task))


@bp.post("/rcm/root-cause-tasks/<tid>/close")
@require_roles("DenialsManager")
def close_task(tid):
    task = find_task(tid)
    if task["status"] != "VERIFIED":
        raise ApiError(ERR_TASK_INVALID_STATE, 409, "Close requires VERIFIED status")
    mon = task.get("monitoring_until_date")
    if mon is None or today() <= parse_date(mon):
        raise ApiError(
            ERR_MONITORING_WINDOW_ACTIVE,
            409,
            "Monitoring window is still active (until %s)" % mon,
        )
    task["status"] = "CLOSED"
    touch(task)
    return ok(public(task))
