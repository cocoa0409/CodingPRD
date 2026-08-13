"""Worker assignments, work logs, wage reconciliations."""

from decimal import Decimal

from flask import Blueprint, g, request

import calc
from calc import d, iso
from common import (ALL_ROLES, ApiError, auth, body, clock_date, created_order,
                    forbid_ownership, get_or_404, invalid, ok, ok_list,
                    paginate, parse_date_val, req_int, stamp_immutable,
                    stamp_new, touch)
from services import (create_recon, end_active_assignment,
                      open_abandonment_audit_case, recompute_recon,
                      recon_for, ser_assignment, ser_reconciliation,
                      ser_work_log, domestic_hired_count)
from store import db

bp = Blueprint("work", __name__)


def _assignment(rid):
    return get_or_404(db.worker_assignments, rid,
                      "ERR_WORKER_ASSIGNMENT_NOT_FOUND", "worker assignment")


@bp.post("/h2a/worker-assignments")
@auth("ContractorAdmin")
def create_assignment():
    b = body()
    worker_id = b.get("worker_id")
    order_id = b.get("job_order_id")
    if worker_id is None:
        raise invalid("worker_id is required")
    w = get_or_404(db.workers, worker_id, "ERR_WORKER_NOT_FOUND", "worker")
    if order_id is None:
        raise invalid("job_order_id is required")
    o = get_or_404(db.job_orders, order_id, "ERR_JOB_ORDER_NOT_FOUND",
                   "job order")
    if o["status"] != "ACTIVE":
        raise ApiError("ERR_JOB_ORDER_INVALID_STATE", 409,
                       "job order must be ACTIVE")
    grower = db.growers.get(o["grower_id"])
    if grower is None or grower["status"] != "ACTIVE":
        raise ApiError("ERR_GROWER_NOT_ACTIVE", 409, "grower is not ACTIVE")
    if w["status"] != "VISA_ISSUED":
        raise ApiError("ERR_WORKER_INVALID_STATE", 409,
                       "worker must be VISA_ISSUED")
    petition = db.visa_petitions.get(w["petition_id"]) if w["petition_id"] \
        else None
    if petition is None or petition["job_order_id"] != o["id"]:
        raise ApiError("ERR_WORKER_ORDER_MISMATCH", 409,
                       "worker's petition does not belong to this job order")
    if any(a["worker_id"] == w["id"] and a["status"] in calc.LIVE_ASSIGNMENT
           for a in db.worker_assignments.values()):
        raise ApiError("ERR_WORKER_ALREADY_ASSIGNED", 409,
                       "worker already has a PLANNED or ACTIVE assignment")
    live = sum(1 for a in db.worker_assignments.values()
               if a["job_order_id"] == o["id"]
               and a["status"] in calc.LIVE_ASSIGNMENT)
    if domestic_hired_count(o["id"]) + live + 1 > o["workers_requested"]:
        raise ApiError("ERR_WORKER_CEILING_EXCEEDED", 409,
                       "workers_requested ceiling would be exceeded")
    rec = {
        "worker_id": w["id"],
        "job_order_id": o["id"],
        "started_on": None,
        "ended_on": None,
        "end_reason": None,
        "status": "PLANNED",
    }
    stamp_new(rec)
    db.worker_assignments[rec["id"]] = rec
    return ok(ser_assignment(rec), 201)


@bp.get("/h2a/worker-assignments")
@auth(*ALL_ROLES)
def list_assignments():
    q = request.args
    rows = list(db.worker_assignments.values())
    for key in ("worker_id", "job_order_id", "status"):
        if q.get(key) is not None:
            rows = [a for a in rows if a[key] == q.get(key)]
    rows = created_order(rows)
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_assignment(a) for a in page], total, limit, offset)


@bp.get("/h2a/worker-assignments/<assignmentId>")
@auth(*ALL_ROLES)
def get_assignment(assignmentId):
    return ok(ser_assignment(_assignment(assignmentId)))


@bp.post("/h2a/worker-assignments/<assignmentId>/start")
@auth("ContractorAdmin")
def start_assignment(assignmentId):
    a = _assignment(assignmentId)
    if a["status"] != "PLANNED":
        raise ApiError("ERR_ASSIGNMENT_INVALID_STATE", 409,
                       "assignment is not PLANNED")
    o = db.job_orders[a["job_order_id"]]
    if clock_date() > d(o["work_end_date"]):
        raise ApiError("ERR_ORDER_PERIOD_ENDED", 409,
                       "clock date is past the order's work_end_date")
    a["status"] = "ACTIVE"
    a["started_on"] = iso(clock_date())
    touch(a)
    w = db.workers[a["worker_id"]]
    if w["status"] == "VISA_ISSUED":
        w["status"] = "WORKING"
        touch(w)
    create_recon(a)
    return ok(ser_assignment(a))


@bp.post("/h2a/worker-assignments/<assignmentId>/end")
@auth("ContractorAdmin")
def end_assignment(assignmentId):
    a = _assignment(assignmentId)
    if a["status"] not in ("PLANNED", "ACTIVE"):
        raise ApiError("ERR_ASSIGNMENT_INVALID_STATE", 409,
                       "assignment is not PLANNED or ACTIVE")
    today = clock_date()
    if a["status"] == "ACTIVE" and today < d(a["started_on"]):
        raise invalid("clock date precedes started_on")
    b = body()
    reason = b.get("end_reason")
    if not isinstance(reason, str) or reason not in calc.END_REASON_ENUM:
        raise invalid("end_reason must be COMPLETED or FOR_CAUSE")
    if a["status"] == "PLANNED":
        if reason != "FOR_CAUSE":
            raise invalid("only FOR_CAUSE may end a PLANNED assignment")
        a["status"] = "TERMINATED"
        a["ended_on"] = iso(today)
        a["end_reason"] = "FOR_CAUSE"
        touch(a)
        return ok(ser_assignment(a))
    end_active_assignment(a, reason, today)
    return ok(ser_assignment(a))


@bp.post("/h2a/worker-assignments/<assignmentId>/report-abandonment")
@auth("ContractorAdmin", "GrowerRep")
def report_abandonment(assignmentId):
    a = db.worker_assignments.get(assignmentId)
    if a is not None and g.user_role == "GrowerRep":
        order = db.job_orders.get(a["job_order_id"])
        if order is None or order["grower_id"] != g.user_id:
            raise forbid_ownership(
                "GrowerRep may report abandonment only on its own grower's "
                "orders")
    if a is None:
        raise ApiError("ERR_WORKER_ASSIGNMENT_NOT_FOUND", 404,
                       "worker assignment not found")
    if a["status"] != "ACTIVE":
        raise ApiError("ERR_ASSIGNMENT_INVALID_STATE", 409,
                       "assignment is not ACTIVE")
    order = db.job_orders[a["job_order_id"]]
    end_active_assignment(a, "ABANDONED", clock_date())
    open_abandonment_audit_case(order)
    return ok(ser_assignment(a))


# ----------------------------------------------------------------- work logs

@bp.post("/h2a/work-logs")
@auth("ContractorAdmin")
def create_work_log():
    b = body()
    assignment_id = b.get("worker_assignment_id")
    if assignment_id is None:
        raise invalid("worker_assignment_id is required")
    a = _assignment(assignment_id)
    if a["status"] != "ACTIVE":
        raise ApiError("ERR_ASSIGNMENT_INVALID_STATE", 409,
                       "assignment must be ACTIVE")
    o = db.job_orders[a["job_order_id"]]
    work_date_s = b.get("work_date")
    work_date = parse_date_val(work_date_s, "work_date")
    lo = d(a["started_on"])
    hi = min(clock_date(), d(o["work_end_date"]))
    if work_date < lo or work_date > hi:
        raise ApiError("ERR_WORK_LOG_DATE_OUT_OF_RANGE", 409,
                       "work_date outside the assignment's working window")
    if any(lg["worker_assignment_id"] == a["id"]
           and lg["work_date"] == work_date_s
           for lg in db.work_logs.values()):
        raise ApiError("ERR_DUPLICATE_WORK_LOG", 409,
                       "a work log already exists for this assignment and date")
    hours = b.get("hours_worked")
    if isinstance(hours, bool) or not isinstance(hours, (int, float)):
        raise ApiError("ERR_INVALID_HOURS", 400,
                       "hours_worked must be a number")
    quarters = Decimal(str(hours)) * 4
    if quarters != int(quarters) or hours <= 0 or hours > 16:
        raise ApiError("ERR_INVALID_HOURS", 400,
                       "hours_worked must be a multiple of 0.25 in (0, 16]")
    units = b.get("units_picked")
    if isinstance(units, bool) or not isinstance(units, int):
        raise invalid("units_picked must be an integer")
    if units < 0:
        raise invalid("units_picked must be >= 0")
    det = db.wage_determinations.get(o["wage_determination_id"])
    piece_rate = calc.effective_piece_rate(o, det) if det else None
    if piece_rate is None and units != 0:
        raise invalid("units_picked must be 0 when no piece rate applies")
    rec = {
        "worker_assignment_id": a["id"],
        "work_date": work_date_s,
        "hours_worked": hours,
        "units_picked": units,
    }
    stamp_immutable(rec)
    db.work_logs[rec["id"]] = rec
    recon = recon_for(a["id"])
    if recon is not None and recon["status"] == "OPEN":
        recompute_recon(recon, final=False)
        touch(recon)
    return ok(ser_work_log(rec), 201)


@bp.get("/h2a/worker-assignments/<assignmentId>/work-logs")
@auth(*ALL_ROLES)
def list_work_logs(assignmentId):
    a = _assignment(assignmentId)
    rows = [lg for lg in db.work_logs.values()
            if lg["worker_assignment_id"] == a["id"]]
    rows = created_order(rows)
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_work_log(lg) for lg in page], total, limit, offset)


@bp.get("/h2a/worker-assignments/<assignmentId>/reconciliation")
@auth(*ALL_ROLES)
def get_reconciliation(assignmentId):
    a = _assignment(assignmentId)
    recon = recon_for(a["id"])
    rows = [recon] if recon is not None else []
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_reconciliation(r) for r in page], total, limit, offset)


@bp.post("/h2a/worker-assignments/<assignmentId>/finalize-reconciliation")
@auth("ContractorAdmin")
def finalize_reconciliation(assignmentId):
    a = _assignment(assignmentId)
    recon = recon_for(a["id"])
    if recon is None or a["status"] not in calc.TERMINAL_ASSIGNMENT \
            or recon["status"] != "OPEN":
        raise ApiError("ERR_RECONCILIATION_INVALID_STATE", 409,
                       "reconciliation must be OPEN on a terminal assignment")
    recon["status"] = "FINALIZED"
    recon["finalized_on"] = iso(clock_date())
    recompute_recon(recon, final=True)
    touch(recon)
    return ok(ser_reconciliation(recon))
