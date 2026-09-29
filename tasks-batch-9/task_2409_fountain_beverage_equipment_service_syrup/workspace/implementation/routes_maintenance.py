"""Preventive maintenance: scheduling, due evaluation, completion, waivers
(PRD 3.5)."""

from flask import Blueprint, g

from calc import brix_calibration_outcome, effective_gallon_interval, maintenance_due_evaluation
from cascade import bump_overdue
from core import (
    TASK_STATUSES,
    TASK_TYPES,
    body,
    db,
    endpoint,
    f_dt,
    f_num,
    f_str,
    get_task,
    get_unit,
    iso_ms,
    new_id,
    now,
    ok,
    ok_list,
    pagination,
    paginate,
    present,
    q_str,
    require,
    sort_rows,
    stamp_new,
    touch,
)
from serialize import ser_task

bp = Blueprint("maintenance", __name__)


# ---------------------------------------------------------------------------
# POST /fountain-network/maintenance-tasks
# ---------------------------------------------------------------------------
@bp.post("/maintenance-tasks")
@endpoint(["ComplianceOfficer"])
def create_task():
    payload = body()
    # rung 3
    unit_id = f_str(payload, "dispenser_unit_id", required=True)
    task_type = f_str(payload, "task_type", required=True, enum=TASK_TYPES)
    due_raw, due_dt = f_dt(payload, "due_at", required=True)
    gallon_interval = f_num(payload, "gallon_interval", gt=0)
    supplied = present(payload, "gallon_interval")
    # rung 5
    unit = get_unit(unit_id)
    # rung 28
    if task_type == "FILTER_CHANGE":
        require(
            supplied,
            "ERR_GALLON_INTERVAL_REQUIRED",
            "gallon_interval is required for a FILTER_CHANGE task.",
        )
    else:
        require(
            not supplied,
            "ERR_GALLON_INTERVAL_NOT_APPLICABLE",
            "gallon_interval is not applicable to a %s task." % task_type,
        )

    outlet = db.outlets[unit["outlet_id"]]
    task = {
        "id": new_id(),
        "dispenser_unit_id": unit["id"],
        "task_type": task_type,
        "due_at": due_raw,
        "_due_at": due_dt,
        "gallon_interval": gallon_interval,
        "status": "SCHEDULED",
        "breach_kind": None,
        "effective_gallon_interval": effective_gallon_interval(
            gallon_interval, outlet["water_hardness_gpg"]
        ),
        "completed_at": None,
        "completed_by_user_id": None,
        "measured_brix_ratio": None,
        "calibration_outcome": None,
        "waiver_reason": None,
        "waived_by_user_id": None,
    }
    stamp_new(task)
    db.tasks[task["id"]] = task
    return ok(ser_task(task), 201)


# ---------------------------------------------------------------------------
# GET /fountain-network/maintenance-tasks/{id}
# ---------------------------------------------------------------------------
@bp.get("/maintenance-tasks/<tid>")
@endpoint(["NetworkAdmin", "ComplianceOfficer", "ServiceTechnician", "OutletManager"])
def read_task(tid):
    return ok(ser_task(get_task(tid)))


# ---------------------------------------------------------------------------
# GET /fountain-network/maintenance-tasks
# ---------------------------------------------------------------------------
@bp.get("/maintenance-tasks")
@endpoint(["NetworkAdmin", "ComplianceOfficer", "ServiceTechnician", "OutletManager"])
def list_tasks():
    limit, offset = pagination()
    unit_id = q_str("dispenser_unit_id")
    task_type = q_str("task_type", enum=TASK_TYPES)
    status = q_str("status", enum=TASK_STATUSES)
    rows = list(db.tasks.values())
    if unit_id is not None:
        rows = [r for r in rows if r["dispenser_unit_id"] == unit_id]
    if task_type is not None:
        rows = [r for r in rows if r["task_type"] == task_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(sort_rows(rows), limit, offset)
    return ok_list([ser_task(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# POST /fountain-network/maintenance-tasks/{id}/evaluate-due
# ---------------------------------------------------------------------------
@bp.post("/maintenance-tasks/<tid>/evaluate-due")
@endpoint(["ComplianceOfficer"])
def evaluate_due(tid):
    # rung 4
    task = get_task(tid)
    # rung 9
    require(
        task["status"] in ("SCHEDULED", "DUE"),
        "ERR_INVALID_STATE_TRANSITION",
        "Due evaluation is declared only from SCHEDULED and DUE.",
    )
    unit = db.units[task["dispenser_unit_id"]]
    outlet = db.outlets[unit["outlet_id"]]

    breach_kind, next_status = maintenance_due_evaluation(task, unit, now())
    if breach_kind is None:
        # nothing breached: status untouched, breach_kind stays null, no version bump
        return ok(ser_task(task))
    if next_status == task["status"] and task["breach_kind"] == breach_kind:
        # already recorded; no declared transition, so nothing is mutated
        return ok(ser_task(task))

    was_overdue = task["status"] == "OVERDUE"
    task["breach_kind"] = breach_kind
    task["status"] = next_status
    touch(task)
    if next_status == "OVERDUE" and not was_overdue:
        bump_overdue(outlet, 1)
    return ok(ser_task(task))


# ---------------------------------------------------------------------------
# POST /fountain-network/maintenance-tasks/{id}/complete
# ---------------------------------------------------------------------------
@bp.post("/maintenance-tasks/<tid>/complete")
@endpoint(["ServiceTechnician"])
def complete_task(tid):
    payload = body()
    # rung 3
    measured = f_num(payload, "measured_brix_ratio")
    # rung 4
    task = get_task(tid)
    unit = db.units[task["dispenser_unit_id"]]
    outlet = db.outlets[unit["outlet_id"]]
    # rung 9
    require(
        task["status"] in ("SCHEDULED", "DUE", "OVERDUE"),
        "ERR_INVALID_STATE_TRANSITION",
        "Only a SCHEDULED, DUE or OVERDUE task can be completed.",
    )
    require(
        unit["status"] != "RETURNED",
        "ERR_INVALID_STATE_TRANSITION",
        "The dispenser unit has already been RETURNED.",
    )
    # rung 29
    if task["task_type"] == "BRIX_CALIBRATION":
        require(
            measured is not None,
            "ERR_BRIX_MEASUREMENT_REQUIRED",
            "measured_brix_ratio is required to complete a BRIX_CALIBRATION task.",
        )

    was_overdue = task["status"] == "OVERDUE"
    task["status"] = "COMPLETED"
    task["completed_at"] = iso_ms(now())
    task["completed_by_user_id"] = g.user_id

    if task["task_type"] == "FILTER_CHANGE":
        unit["gallons_at_last_filter_change"] = unit["lifetime_dispensed_gallons"]
        touch(unit)
    elif task["task_type"] == "BRIX_CALIBRATION":
        outcome = brix_calibration_outcome(measured)
        task["measured_brix_ratio"] = measured
        task["calibration_outcome"] = outcome
        unit["brix_ratio_last_measured"] = measured
        unit["calibration_status"] = "IN_SPEC" if outcome == "PASS" else "OUT_OF_SPEC"
        touch(unit)
    touch(task)

    if was_overdue:
        bump_overdue(outlet, -1)
    return ok(ser_task(task))


# ---------------------------------------------------------------------------
# POST /fountain-network/maintenance-tasks/{id}/waive
# ---------------------------------------------------------------------------
@bp.post("/maintenance-tasks/<tid>/waive")
@endpoint(["ComplianceOfficer"])
def waive_task(tid):
    payload = body()
    # rung 3
    waiver_reason = f_str(payload, "waiver_reason", required=True)
    # rung 4
    task = get_task(tid)
    unit = db.units[task["dispenser_unit_id"]]
    outlet = db.outlets[unit["outlet_id"]]
    # rung 9
    require(
        task["status"] in ("DUE", "OVERDUE"),
        "ERR_INVALID_STATE_TRANSITION",
        "Only a DUE or OVERDUE task can be waived.",
    )
    # rung 17
    require(
        outlet["last_hold_placed_by_user_id"] is None
        or g.user_id != outlet["last_hold_placed_by_user_id"],
        "ERR_WAIVER_SEGREGATION_VIOLATION",
        "The officer who placed the outlet's compliance hold may not waive its tasks.",
    )

    was_overdue = task["status"] == "OVERDUE"
    task["status"] = "WAIVED"
    task["waiver_reason"] = waiver_reason
    task["waived_by_user_id"] = g.user_id
    touch(task)
    if was_overdue:
        bump_overdue(outlet, -1)
    return ok(ser_task(task))
