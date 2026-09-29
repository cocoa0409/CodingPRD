"""RetreadLine, RetreadJob and Technician."""

from flask import Blueprint, g

import calc
import common
import derive
import errors
import serialize
import validate as v
from auth import endpoint, fleet_scope, is_fleet_manager
from db import db, insert, touch
from errors import fail
from response import created, ok
from util import whole_minutes

bp = Blueprint("plant", __name__)


# ================================================================ RetreadLine

@bp.post("/service-locations/<location_id>/retread-lines")
@endpoint("DealerAdmin")
def create_line(location_id):
    location_row = common.location(location_id)
    payload = v.body()
    line_code = v.s_str(payload, "line_code")
    cooldown = v.s_int(payload, "cure_cooldown_minutes", required=False, minimum=0, maximum=240)
    if cooldown is None:
        cooldown = 30
    for row in db.retread_lines.values():
        if row["service_location_id"] == location_row["id"] and row["line_code"] == line_code:
            fail(errors.ERR_DUPLICATE_LINE_CODE)
    row = insert(
        db.retread_lines,
        {
            "service_location_id": location_row["id"],
            "line_code": line_code,
            "cure_cooldown_minutes": cooldown,
            "status": "AVAILABLE",
        },
    )
    return created(serialize.retread_line(row))


@bp.post("/retread-lines/<line_id>/status")
@endpoint("DealerAdmin")
def set_line_status(line_id):
    row = common.retread_line(line_id)
    payload = v.body()
    status = v.s_enum(payload, "status", ("AVAILABLE", "DOWN"))
    if row["status"] == status:
        fail(errors.ERR_LINE_INVALID_STATE)
    row["status"] = status
    touch(row)
    return ok(serialize.retread_line(row))


@bp.get("/retread-lines/<line_id>")
@endpoint("DealerAdmin", "PlantScheduler")
def get_line(line_id):
    return ok(serialize.retread_line(common.retread_line(line_id)))


@bp.get("/retread-lines")
@endpoint("DealerAdmin", "PlantScheduler")
def list_lines():
    rows = common.filtered(
        db.retread_lines,
        [
            ("service_location_id", v.q_str("service_location_id")),
            ("status", v.q_enum("status", ("AVAILABLE", "DOWN"))),
        ],
    )
    return common.page(rows, serialize.retread_line)


# ================================================================ RetreadJob

def _slot_minutes_or_fail(start_dt, end_dt):
    minutes = whole_minutes(start_dt, end_dt)
    if minutes is None or minutes < calc.MIN_JOB_MINUTES or minutes > calc.MAX_JOB_MINUTES:
        fail(errors.ERR_INVALID_SLOT_DURATION)
    return minutes


@bp.post("/retread-jobs")
@endpoint("PlantScheduler")
def create_job():
    payload = v.body()
    casing_id = v.s_str(payload, "casing_id")
    retread_line_id = v.s_str(payload, "retread_line_id")
    tread_design_code = v.s_str(payload, "tread_design_code")
    start_raw, start_dt = v.s_datetime(payload, "scheduled_start_at")
    end_raw, end_dt = v.s_datetime(payload, "scheduled_end_at")
    casing_row = common.casing(casing_id)
    line_row = common.retread_line(retread_line_id)

    if casing_row["status"] != "INSPECTED" or casing_row["inspection_grade"] not in ("A", "B", "C"):
        fail(errors.ERR_CASING_INVALID_STATE)

    policy = derive.find_policy(casing_row["fleet_account_id"], casing_row["intended_position"])
    if policy is not None and not casing_row["retread_count"] < policy["max_retread_count"]:
        fail(errors.ERR_MAX_RETREAD_COUNT_REACHED)
    if policy is None:
        fail(errors.ERR_TIRE_POLICY_MISSING)

    if calc.slot_conflict(line_row, start_dt, end_dt):
        fail(errors.ERR_RETREAD_SLOT_CONFLICT)
    slot_minutes = _slot_minutes_or_fail(start_dt, end_dt)

    fleet_row = db.fleet_accounts.get(casing_row["fleet_account_id"])
    if fleet_row is not None and fleet_row["status"] != "ACTIVE":
        fail(errors.ERR_FLEET_SUSPENDED)
    if line_row["status"] != "AVAILABLE":
        fail(errors.ERR_LINE_DOWN)

    row = insert(
        db.retread_jobs,
        {
            "casing_id": casing_row["id"],
            "retread_line_id": line_row["id"],
            "tread_design_code": tread_design_code,
            "scheduled_start_at": start_raw,
            "scheduled_start_at_dt": start_dt,
            "scheduled_end_at": end_raw,
            "scheduled_end_at_dt": end_dt,
            "slot_minutes": slot_minutes,
            "status": "SCHEDULED",
            "grade_at_scheduling": casing_row["inspection_grade"],
            "retread_count_at_scheduling": casing_row["retread_count"],
            "warranty_months": None,
            "warranty_expires_on": None,
            "produced_tire_asset_id": None,
            "completed_at": None,
            "completed_at_dt": None,
            "failure_reason": None,
            "reschedule_count": 0,
        },
    )
    casing_row["status"] = "RETREAD_QUEUED"
    touch(casing_row)
    return created(serialize.retread_job(row))


@bp.post("/retread-jobs/<job_id>/start")
@endpoint("PlantScheduler")
def start_job(job_id):
    row = common.retread_job(job_id)
    payload = v.body()
    started_raw, started_dt = v.s_datetime(payload, "started_at")
    if row["status"] != "SCHEDULED":
        fail(errors.ERR_RETREAD_JOB_INVALID_STATE)
    if started_dt < row["scheduled_start_at_dt"]:
        fail(errors.ERR_JOB_START_TOO_EARLY)
    line_row = db.retread_lines.get(row["retread_line_id"])
    if line_row is not None and line_row["status"] != "AVAILABLE":
        fail(errors.ERR_LINE_DOWN)
    row["status"] = "IN_PRODUCTION"
    touch(row)
    casing_row = db.casings.get(row["casing_id"])
    if casing_row is not None and casing_row["status"] == "RETREAD_QUEUED":
        casing_row["status"] = "IN_RETREAD"
        touch(casing_row)
    return ok(serialize.retread_job(row))


@bp.post("/retread-jobs/<job_id>/complete")
@endpoint("PlantScheduler")
def complete_job(job_id):
    row = common.retread_job(job_id)
    payload = v.body()
    completed_raw, completed_dt = v.s_datetime(payload, "completed_at")
    cost_basis_cents = v.s_int(payload, "cost_basis_cents", minimum=0)
    if row["status"] != "IN_PRODUCTION":
        fail(errors.ERR_RETREAD_JOB_INVALID_STATE)
    if completed_dt < row["scheduled_start_at_dt"]:
        fail(errors.ERR_INVALID_TIMELINE)

    casing_row = db.casings.get(row["casing_id"])
    fleet_row = db.fleet_accounts.get(casing_row["fleet_account_id"]) if casing_row else None

    # hop 1
    months, expires_on = calc.warranty(
        row["grade_at_scheduling"], row["retread_count_at_scheduling"], completed_dt
    )
    asset = insert(
        db.tire_assets,
        {
            "fleet_account_id": casing_row["fleet_account_id"],
            "casing_id": casing_row["id"],
            "brand": casing_row["brand"],
            "cost_basis_cents": cost_basis_cents,
            "vehicle_id": None,
            "position": None,
            "status": "IN_INVENTORY",
            "mounted_at": None,
            "mounted_at_dt": None,
            "odometer_at_mount": None,
            "tread_depth_at_mount_32nds": None,
            "replaced_tire_asset_id": None,
            "pull_reason": None,
        },
    )
    row["status"] = "COMPLETED"
    row["completed_at"] = completed_raw
    row["completed_at_dt"] = completed_dt
    row["warranty_months"] = months
    row["warranty_expires_on"] = expires_on
    row["produced_tire_asset_id"] = asset["id"]
    touch(row)

    # hop 2
    casing_row["status"] = "RETREADED"
    casing_row["retread_count"] = casing_row["retread_count"] + 1
    casing_row["inspection_grade"] = None
    touch(casing_row)

    # hop 3
    delta = calc.credit_adjustment_delta_cents(
        casing_row["fleet_account_id"],
        row["grade_at_scheduling"],
        row["retread_count_at_scheduling"],
        db.clock_date(),
    )
    common.post_entry(
        fleet_row,
        "ADJUSTMENT",
        delta,
        "RETREAD_JOB",
        row["id"],
        "Production-verified casing credit adjustment",
        casing_id=casing_row["id"],
    )

    # hop 4 and hop 5
    touch(fleet_row)
    common.refresh_open_invoices(fleet_row)
    return ok(serialize.retread_job(row))


@bp.post("/retread-jobs/<job_id>/fail-cure")
@endpoint("PlantScheduler")
def fail_cure_job(job_id):
    row = common.retread_job(job_id)
    payload = v.body()
    failure_reason = v.s_enum(
        payload, "failure_reason", ("CURE_DEFECT", "LINE_FAULT", "CASING_FAILURE")
    )
    v.s_str(payload, "note", required=False)
    if row["status"] != "IN_PRODUCTION":
        fail(errors.ERR_RETREAD_JOB_INVALID_STATE)
    row["status"] = "FAILED_CURE"
    row["failure_reason"] = failure_reason
    touch(row)

    casing_row = db.casings.get(row["casing_id"])
    line_row = db.retread_lines.get(row["retread_line_id"])
    if failure_reason in ("CURE_DEFECT", "LINE_FAULT"):
        if casing_row is not None and casing_row["status"] == "IN_RETREAD":
            casing_row["status"] = "INSPECTED"
            touch(casing_row)
        if failure_reason == "LINE_FAULT" and line_row is not None and line_row["status"] == "AVAILABLE":
            line_row["status"] = "DOWN"
            touch(line_row)
    else:
        if casing_row is not None and casing_row["status"] == "IN_RETREAD":
            casing_row["status"] = "REJECTED"
            casing_row["rejection_reason"] = "CASING_FAILURE_IN_PRODUCTION"
            touch(casing_row)
    return ok(serialize.retread_job(row))


@bp.post("/retread-jobs/<job_id>/reschedule")
@endpoint("PlantScheduler")
def reschedule_job(job_id):
    row = common.retread_job(job_id)
    payload = v.body()
    start_raw, start_dt = v.s_datetime(payload, "scheduled_start_at")
    end_raw, end_dt = v.s_datetime(payload, "scheduled_end_at")
    line_id = v.s_str(payload, "retread_line_id", required=False)
    line_row = common.retread_line(line_id) if line_id is not None else db.retread_lines.get(
        row["retread_line_id"]
    )

    if row["status"] != "FAILED_CURE":
        fail(errors.ERR_RETREAD_JOB_INVALID_STATE)
    casing_row = db.casings.get(row["casing_id"])
    if casing_row is None or casing_row["status"] != "INSPECTED":
        fail(errors.ERR_CASING_INVALID_STATE)

    if calc.slot_conflict(line_row, start_dt, end_dt, exclude_job_id=row["id"]):
        fail(errors.ERR_RETREAD_SLOT_CONFLICT)
    slot_minutes = _slot_minutes_or_fail(start_dt, end_dt)
    if line_row["status"] != "AVAILABLE":
        fail(errors.ERR_LINE_DOWN)

    row["status"] = "SCHEDULED"
    row["retread_line_id"] = line_row["id"]
    row["scheduled_start_at"] = start_raw
    row["scheduled_start_at_dt"] = start_dt
    row["scheduled_end_at"] = end_raw
    row["scheduled_end_at_dt"] = end_dt
    row["slot_minutes"] = slot_minutes
    row["reschedule_count"] = row["reschedule_count"] + 1
    touch(row)
    casing_row["status"] = "RETREAD_QUEUED"
    touch(casing_row)
    return ok(serialize.retread_job(row))


@bp.post("/retread-jobs/<job_id>/cancel")
@endpoint("PlantScheduler")
def cancel_job(job_id):
    row = common.retread_job(job_id)
    payload = v.body()
    v.s_str(payload, "reason")
    if row["status"] not in ("SCHEDULED", "FAILED_CURE"):
        fail(errors.ERR_RETREAD_JOB_INVALID_STATE)
    from_scheduled = row["status"] == "SCHEDULED"
    row["status"] = "CANCELLED"
    touch(row)
    if from_scheduled:
        casing_row = db.casings.get(row["casing_id"])
        if casing_row is not None and casing_row["status"] == "RETREAD_QUEUED":
            casing_row["status"] = "INSPECTED"
            touch(casing_row)
    return ok(serialize.retread_job(row))


@bp.get("/retread-jobs/<job_id>")
@endpoint("DealerAdmin", "PlantScheduler", "FleetManager")
def get_job(job_id):
    row = common.retread_job(job_id)
    casing_row = db.casings.get(row["casing_id"])
    if casing_row is not None:
        fleet_scope(casing_row["fleet_account_id"])
    return ok(serialize.retread_job(row))


@bp.get("/retread-jobs")
@endpoint("DealerAdmin", "PlantScheduler", "FleetManager")
def list_jobs():
    casing_id = v.q_str("casing_id")
    retread_line_id = v.q_str("retread_line_id")
    produced_tire_asset_id = v.q_str("produced_tire_asset_id")
    status = v.q_enum("status", derive.JOB_STATUSES)
    rows = []
    for row in db.retread_jobs.values():
        if casing_id is not None and row["casing_id"] != casing_id:
            continue
        if retread_line_id is not None and row["retread_line_id"] != retread_line_id:
            continue
        if produced_tire_asset_id is not None and row["produced_tire_asset_id"] != produced_tire_asset_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if is_fleet_manager():
            casing_row = db.casings.get(row["casing_id"])
            if casing_row is None or casing_row["fleet_account_id"] != g.user_id:
                continue
        rows.append(row)
    from db import ordered

    return common.page(ordered(rows), serialize.retread_job)


# ================================================================ Technician

@bp.post("/service-locations/<location_id>/technicians")
@endpoint("DealerAdmin")
def create_technician(location_id):
    location_row = common.location(location_id)
    payload = v.body()
    name = v.s_str(payload, "name")
    certification_level = v.s_enum(payload, "certification_level", derive.CERT_LEVELS)
    row = insert(
        db.technicians,
        {
            "service_location_id": location_row["id"],
            "name": name,
            "certification_level": certification_level,
            "status": "AVAILABLE",
        },
    )
    return created(serialize.technician(row))


@bp.post("/technicians/<technician_id>/status")
@endpoint("DealerAdmin")
def set_technician_status(technician_id):
    row = common.technician(technician_id)
    payload = v.body()
    status = v.s_enum(payload, "status", ("AVAILABLE", "ON_CALL", "OFF_DUTY"))
    if status == "OFF_DUTY" and row["status"] in ("AVAILABLE", "ON_CALL"):
        pass
    elif status == "AVAILABLE" and row["status"] == "OFF_DUTY":
        pass
    else:
        fail(errors.ERR_TECHNICIAN_INVALID_STATE)
    row["status"] = status
    touch(row)
    return ok(serialize.technician(row))


@bp.get("/technicians/<technician_id>")
@endpoint("DealerAdmin", "DispatchCoordinator", "TireTechnician")
def get_technician(technician_id):
    return ok(serialize.technician(common.technician(technician_id)))


@bp.get("/technicians")
@endpoint("DealerAdmin", "DispatchCoordinator", "TireTechnician")
def list_technicians():
    rows = common.filtered(
        db.technicians,
        [
            ("service_location_id", v.q_str("service_location_id")),
            ("status", v.q_enum("status", ("AVAILABLE", "ON_CALL", "OFF_DUTY"))),
            ("certification_level", v.q_enum("certification_level", derive.CERT_LEVELS)),
        ],
    )
    return common.page(rows, serialize.technician)
