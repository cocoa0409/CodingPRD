from flask import Blueprint, request

from db import store
from middleware import authenticate, require_roles
from common import (
    get_json_body, require_string, require_enum, opt_int, opt_bool,
    get_or_404, make_entity, touch, parse_pagination, paginate,
)
from clock import parse_datetime
from response import success, success_list
from errors import (
    err, ERR_FORBIDDEN, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_INVALID_STATE, ERR_TASK_DUE_AFTER_DEADLINE,
)
from services.applications import recompute_open_task_count
from services.billing import append_billing_entry
from services.calculations import recompute_contract_balances, recompute_balances_for_student

bp = Blueprint("application_tasks", __name__)

# allowed transitions for ApplicationTask state machine
TASK_TRANSITIONS = {
    ("OPEN", "IN_PROGRESS"),
    ("IN_PROGRESS", "DONE"),
    ("OPEN", "BLOCKED"),
    ("IN_PROGRESS", "BLOCKED"),
    ("BLOCKED", "OPEN"),
    ("OPEN", "WAIVED"),
    ("IN_PROGRESS", "WAIVED"),
    ("BLOCKED", "WAIVED"),
}
TASK_TARGETS = {"OPEN", "IN_PROGRESS", "BLOCKED", "DONE", "WAIVED"}


def serialize(t):
    return {
        "id": t["id"],
        "application_id": t["application_id"],
        "title": t["title"],
        "task_type": t["task_type"],
        "due_utc": t["due_utc"],
        "estimated_cost_cents": t["estimated_cost_cents"],
        "blocks_submission": t["blocks_submission"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


@bp.route("/application-tasks", methods=["POST"])
def create_task():
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    body = get_json_body()
    application_id = require_string(body, "application_id")
    title = require_string(body, "title")
    task_type = require_enum(body, "task_type", {"ESSAY", "RECOMMENDATION", "FORM", "FEE", "TRANSCRIPT"})
    due_raw = require_string(body, "due_utc")
    estimated_cost_cents = opt_int(body, "estimated_cost_cents", 0)
    if estimated_cost_cents < 0:
        raise err(ERR_INVALID_REQUEST, "estimated_cost_cents must be >= 0")
    blocks_submission = opt_bool(body, "blocks_submission", True)
    due = parse_datetime(due_raw)

    with store.lock:
        app = store.applications.get(application_id)
        if app is None:
            raise err(ERR_REFERENCE_NOT_FOUND, "application_id does not reference an existing application")
        _assert_owner(caller, app)
        # due_utc must be <= deadline (closed boundary)
        if due > parse_datetime(app["deadline_utc"]):
            raise err(ERR_TASK_DUE_AFTER_DEADLINE, "Task due_utc is after the application deadline")

        t = make_entity()
        t.update({
            "application_id": application_id,
            "title": title,
            "task_type": task_type,
            "due_utc": due_raw,
            "estimated_cost_cents": estimated_cost_cents,
            "blocks_submission": blocks_submission,
            "status": "OPEN",
        })
        store.application_tasks[t["id"]] = t
        recompute_open_task_count(app)
        touch(app)
        # A new OPEN billable task changes the projected pending-task cost, so
        # the student's contract projected balances must be reconciled (PRD §3.7
        # defines projected_balance_cents = retainer_balance_cents - pending cost).
        recompute_balances_for_student(app["student_id"])
        return success(serialize(t), 201)


@bp.route("/application-tasks/<task_id>", methods=["GET"])
def get_task(task_id):
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    with store.lock:
        t = get_or_404(store.application_tasks, task_id)
        _assert_access(caller, t)
        return success(serialize(t))


@bp.route("/application-tasks", methods=["GET"])
def list_tasks():
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    limit, offset = parse_pagination()
    filt_app = request.args.get("application_id")
    filt_status = request.args.get("status")
    with store.lock:
        rows = [r for r in store.application_tasks.values() if _visible(caller, r)]
        if filt_app is not None:
            rows = [r for r in rows if r.get("application_id") == filt_app]
        if filt_status is not None:
            rows = [r for r in rows if r.get("status") == filt_status]
        page, total = paginate(rows, limit, offset)
        return success_list([serialize(r) for r in page], limit, offset, total)


@bp.route("/application-tasks/<task_id>/transition", methods=["POST"])
def transition_task(task_id):
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    body = get_json_body()
    to_status = require_enum(body, "to_status", TASK_TARGETS)
    with store.lock:
        t = get_or_404(store.application_tasks, task_id)
        app = store.applications.get(t["application_id"])
        _assert_owner(caller, app)
        cur = t["status"]
        if (cur, to_status) not in TASK_TRANSITIONS:
            raise err(ERR_INVALID_STATE, "Cannot transition task %s -> %s" % (cur, to_status))

        t["status"] = to_status
        touch(t)

        if to_status == "DONE":
            _maybe_bill_task(t, app)

        recompute_open_task_count(app)
        touch(app)
        # Any task transition can move a task into or out of the pending set
        # (OPEN/IN_PROGRESS/BLOCKED), which changes the contract's projected
        # balance per PRD §3.7. Reconcile the student's contract balances.
        recompute_balances_for_student(app["student_id"])
        return success(serialize(t))


def _maybe_bill_task(task, app):
    """On DONE: if task_type != ESSAY and estimated_cost_cents > 0 and the
    student has an ACTIVE contract, append a CHARGE."""
    if task["task_type"] == "ESSAY":
        return
    if task.get("estimated_cost_cents", 0) <= 0:
        return
    student_id = app["student_id"]
    contract = _active_contract_for_student(student_id)
    if contract is None:
        return
    append_billing_entry(
        contract=contract,
        entry_type="CHARGE",
        source_kind="TASK",
        amount_cents=task["estimated_cost_cents"],
        source_id=task["id"],
        minutes=0,
        memo="",
        recompute=True,
    )


def _active_contract_for_student(student_id):
    for c in store.contracts.values():
        if c.get("student_id") == student_id and c.get("status") == "ACTIVE":
            return c
    return None


def _assert_owner(caller, app):
    if app is None:
        raise err(ERR_FORBIDDEN, "Not permitted")
    student = store.students.get(app.get("student_id"))
    if student is None or student.get("counselor_id") != caller.user_id:
        raise err(ERR_FORBIDDEN, "Counselor does not own this task")


def _visible(caller, t):
    app = store.applications.get(t.get("application_id"))
    if app is None:
        return False
    student = store.students.get(app.get("student_id"))
    if student is None:
        return False
    if caller.is_counselor:
        return student.get("counselor_id") == caller.user_id
    if caller.is_student:
        return student["id"] == caller.user_id
    return False


def _assert_access(caller, t):
    if not _visible(caller, t):
        raise err(ERR_FORBIDDEN, "Not permitted on this task")
