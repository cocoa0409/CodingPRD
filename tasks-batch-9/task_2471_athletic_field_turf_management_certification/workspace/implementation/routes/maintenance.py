"""The maintenance programme (PRD 3.2) and its completion side effects (PRD 3.7)."""

import calc
import derive
import errors
import middleware
import response
import validate
from db import bump, common_fields, db, new_id, now
from errors import ApiError
from routes.blueprint import bp
from routes.common import listing

FILTERS = {
    "field_id": "field_id",
    "assigned_staff_member_id": "assigned_staff_member_id",
    "task_type": "task_type",
    "status": "status",
    "planned_for_certification_window": "planned_for_certification_window",
}


@bp.post("/maintenance-tasks")
def create_task():
    middleware.authenticate(["TurfAgronomist", "FieldOperationsCoordinator"])
    body = validate.Body(
        required=["field_id", "assigned_staff_member_id", "task_type",
                  "scheduled_start_utc", "scheduled_end_utc"],
        optional=["planned_for_certification_window", "nitrogen_lb_per_1000_sq_ft"])

    field_id = body.string("field_id")
    staff_id = body.string("assigned_staff_member_id")
    task_type = body.enum("task_type", calc.TASK_TYPES)
    start = body.instant("scheduled_start_utc")
    end = body.instant("scheduled_end_utc")
    planned = body.boolean("planned_for_certification_window", default=False)
    nitrogen = body.number("nitrogen_lb_per_1000_sq_ft",
                           calc.r2(0), calc.r2("6.00"))

    field = middleware.body_field(field_id)          # priority 18
    middleware.body_staff(staff_id)                  # priority 19

    # priority 27 - the fertility-rate rule
    if task_type == "FERTILITY" and nitrogen is None:
        raise ApiError("ERR_FERTILITY_RATE_MISMATCH", 422,
                       "nitrogen_lb_per_1000_sq_ft is required for a FERTILITY task.")
    if task_type != "FERTILITY" and nitrogen is not None:
        raise ApiError(
            "ERR_FERTILITY_RATE_MISMATCH", 422,
            "nitrogen_lb_per_1000_sq_ft must be absent for a %s task." % task_type)

    # priority 28 - the surface-class rule
    expected = ("NATURAL_GRASS" if task_type in calc.NATURAL_TASK_TYPES
                else "SYNTHETIC_TURF")
    if field["surface_type"] != expected:
        raise ApiError("ERR_TASK_TYPE_SURFACE_MISMATCH", 422,
                       "%s may only be scheduled on a %s field." % (task_type, expected))

    # priority 29 - the window rule
    if end.dt <= start.dt:
        raise ApiError("ERR_INVALID_WINDOW", 422,
                       "scheduled_end_utc must be strictly after scheduled_start_utc.")

    # priority 34 - the retirement guard
    if field["retired_at"] is not None:
        raise ApiError("ERR_FIELD_RETIRED", 409,
                       "No maintenance may be scheduled on a retired field.")

    # priority 63 - INTERVAL SEMANTICS B: closed intervals, aggregate capacity
    concurrent = 0
    for other in db.maintenance_tasks.values():
        if (other["assigned_staff_member_id"] == staff_id
                and other["status"] in ("SCHEDULED", "IN_PROGRESS")
                and other["scheduled_start_utc"].dt <= end.dt
                and start.dt <= other["scheduled_end_utc"].dt):
            concurrent += 1
    if concurrent >= calc.MAX_CONCURRENT_STAFF_TASKS:
        raise ApiError("ERR_STAFF_TASK_CAPACITY_EXCEEDED", 409,
                       "That staff member already holds two concurrent tasks.")

    # priority 64 - INTERVAL SEMANTICS C: strict overlap, no buffer
    for booking in db.usage_bookings.values():
        if (booking["field_id"] == field_id
                and booking["status"] in ("SCHEDULED", "CONFIRMED")
                and start.dt < booking["window_end_utc"].dt
                and booking["window_start_utc"].dt < end.dt):
            raise ApiError("ERR_TASK_CONFLICTS_WITH_BOOKING", 409,
                           "The maintenance window overlaps an existing booking.")

    task = {
        "id": new_id(),
        "field_id": field_id,
        "assigned_staff_member_id": staff_id,
        "task_type": task_type,
        "scheduled_start_utc": start,
        "scheduled_end_utc": end,
        "planned_for_certification_window": planned,
        "nitrogen_lb_per_1000_sq_ft": (calc.r2(nitrogen)
                                       if nitrogen is not None else None),
        "surface_class": field["surface_type"],
        "recovery_credit_hours": calc.RECOVERY_CREDIT_HOURS[task_type],
        "status": "SCHEDULED",
        "started_at_utc": None,
        "completed_at_utc": None,
        "cancellation_reason": None,
    }
    task.update(common_fields())
    db.maintenance_tasks[task["id"]] = task
    return response.created(task)


@bp.get("/maintenance-tasks")
def list_tasks():
    middleware.authenticate(middleware.ALL_ROLES)
    return listing(db.maintenance_tasks, FILTERS)


@bp.get("/maintenance-tasks/<task_id>")
def read_task(task_id):
    middleware.authenticate(middleware.ALL_ROLES)
    return response.ok(middleware.task_or_404(task_id))


@bp.post("/maintenance-tasks/<task_id>/transition")
def transition_task(task_id):
    middleware.authenticate(["TurfAgronomist", "FieldOperationsCoordinator"])
    task = middleware.task_or_404(task_id)
    body = validate.Body(required=["action"],
                         optional=["completed_at_utc", "cancellation_reason"])
    action = body.enum("action", ["START", "COMPLETE", "CANCEL"])
    completed_at = body.instant("completed_at_utc")
    reason = body.string("cancellation_reason", 1, 500)

    current = now()
    if action == "COMPLETE":
        if completed_at is None:
            raise errors.invalid_request(
                "completed_at_utc is required for the COMPLETE action.")
        if completed_at.dt > current.dt:
            raise errors.invalid_request(
                "completed_at_utc may not be later than the current instant.")
    if action == "CANCEL" and reason is None:
        raise errors.invalid_request(
            "cancellation_reason is required for the CANCEL action.")

    field = db.fields[task["field_id"]]

    if action == "START":
        # PRD 3.2: a task on a field that has already been retired cannot be started
        if field["retired_at"] is not None:
            raise ApiError("ERR_FIELD_RETIRED", 409,
                           "The field this task belongs to has been retired.")
        if task["status"] != "SCHEDULED":
            raise _not_transitionable(action)
        task["status"] = "IN_PROGRESS"
        task["started_at_utc"] = current
        bump(task)
        return response.ok(task)

    if action == "COMPLETE":
        if task["status"] != "IN_PROGRESS":
            raise _not_transitionable(action)
        if completed_at.dt < task["started_at_utc"].dt:
            raise errors.invalid_request(
                "completed_at_utc may not be earlier than started_at_utc.")

        debt_before = field["rest_debt_hours"]
        task["status"] = "COMPLETED"
        task["completed_at_utc"] = completed_at
        bump(task)

        derive.recompute_field(field)
        absorbed = calc.r2(debt_before - field["rest_debt_hours"])
        # PRD 3.7: no entry at all when the capped credit works out to 0.00
        if absorbed > calc.ZERO:
            derive.append_ledger(
                field, "RECOVERY_CREDIT", calc.ZERO,
                rest_credit_hours=absorbed,
                maintenance_task_id=task["id"],
                note="MAINTENANCE_TASK_COMPLETED_RECOVERY_CREDIT")
        derive.touch_field(field)
        return response.ok(task)

    if task["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise _not_transitionable(action)
    task["status"] = "CANCELLED"
    task["cancellation_reason"] = reason
    bump(task)
    # PRD 3.2: cancellation grants no rest credit and appends no ledger entry.
    derive.recompute_field(field)
    return response.ok(task)


def _not_transitionable(action):
    return ApiError("ERR_TASK_NOT_TRANSITIONABLE", 409,
                    "The task's current status does not permit %s." % action)
