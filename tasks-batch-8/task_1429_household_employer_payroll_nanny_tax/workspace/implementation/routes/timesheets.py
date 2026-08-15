"""Timesheet endpoints and the approval cascade (PRD 3.5)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_TIMESHEET_OVERLAP,
    ERR_NO_ACTIVE_AGREEMENT,
)
from middleware import require_roles, check_employer_ownership
from response import success_object, success_list
from routes.workers import get_worker_or_404
from services.payroll import agreement_covers_period
from services.serializers import serialize_timesheet
from util import (
    apply_filters,
    get_json_body,
    is_int,
    paginate,
    parse_date,
    parse_pagination,
    require_date,
    require_field,
    sort_by_created_at,
)

bp = Blueprint("timesheets", __name__)


def get_timesheet_or_404(timesheet_id: str) -> dict:
    ts = db.timesheets.get(timesheet_id)
    if ts is None:
        raise_err(ERR_NOT_FOUND, "Timesheet id does not exist")
    return ts


def _check_read_access(ts: dict, user_id: str, role: str) -> None:
    worker = db.workers.get(ts["worker_id"])
    if worker is not None:
        check_employer_ownership(user_id, role, worker["employer_id"])
    if role == "Worker" and user_id != ts["worker_id"]:
        from middleware import forbid

        forbid("Worker may only access their own timesheets")


@bp.route("/household-payroll/workers/<worker_id>/timesheets", methods=["POST"])
@require_roles("Worker")
def create_timesheet(worker_id: str, _user_id: str, _role: str):
    worker = get_worker_or_404(worker_id)
    if _user_id != worker_id:
        from middleware import forbid

        forbid("Worker may only create timesheets for themselves")

    body = get_json_body()
    period_start = require_date(body, "period_start")
    period_end = require_date(body, "period_end")
    if period_end <= period_start:
        raise_err(ERR_INVALID_REQUEST, "period_end must be after period_start (half-open interval)")

    entries = require_field(body, "entries")
    if not isinstance(entries, list):
        raise_err(ERR_INVALID_REQUEST, "entries must be an array")
    seen_dates: set[str] = set()
    total = 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise_err(ERR_INVALID_REQUEST, "entries items must be objects")
        work_date = parse_date(entry.get("work_date"), "entries[].work_date")
        minutes = entry.get("worked_minutes")
        if not is_int(minutes) or minutes < 0:
            raise_err(ERR_INVALID_REQUEST, "entries[].worked_minutes must be a non-negative integer")
        if not (period_start <= work_date < period_end):
            raise_err(ERR_INVALID_REQUEST, "work_date must lie inside [period_start, period_end)")
        if work_date in seen_dates:
            raise_err(ERR_INVALID_REQUEST, "work_date must be unique within the timesheet")
        seen_dates.add(work_date)
        total += minutes

    if worker["status"] not in ("CLASSIFIED", "ACTIVE"):
        raise_err(ERR_INVALID_STATE, "Timesheet create requires worker CLASSIFIED or ACTIVE")

    # Half-open overlap against the worker's non-LOCKED timesheets; adjacency allowed.
    for other in db.timesheets.values():
        if other["worker_id"] != worker_id or other["status"] == "LOCKED":
            continue
        if period_start < other["period_end"] and other["period_start"] < period_end:
            raise_err(ERR_TIMESHEET_OVERLAP, "Timesheet period overlaps an existing timesheet")

    if agreement_covers_period(worker_id, period_start, period_end) is None:
        raise_err(ERR_NO_ACTIVE_AGREEMENT, "No ACTIVE agreement covers the timesheet period")

    ts = {
        "worker_id": worker_id,
        "pay_run_id": None,
        "period_start": period_start,
        "period_end": period_end,
        "entries": entries,
        "total_worked_minutes": total,
        "status": "DRAFT",
        "submitted_at": None,
    }
    db.stamp_new(ts)
    db.timesheets[ts["id"]] = ts
    return success_object(serialize_timesheet(ts), 201)


@bp.route("/household-payroll/timesheets/<timesheet_id>/submit", methods=["POST"])
@require_roles("Worker")
def submit_timesheet(timesheet_id: str, _user_id: str, _role: str):
    ts = get_timesheet_or_404(timesheet_id)
    if _user_id != ts["worker_id"]:
        from middleware import forbid

        forbid("Worker may only submit their own timesheets")
    if ts["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only a DRAFT timesheet can be submitted")
    if ts["total_worked_minutes"] <= 0:
        raise_err(ERR_INVALID_REQUEST, "total_worked_minutes must be greater than 0")
    ts["status"] = "SUBMITTED"
    ts["submitted_at"] = db.now_iso()
    db.touch(ts)
    return success_object(serialize_timesheet(ts))


@bp.route("/household-payroll/timesheets/<timesheet_id>/approve", methods=["POST"])
@require_roles("HouseholdClient")
def approve_timesheet(timesheet_id: str, _user_id: str, _role: str):
    ts = get_timesheet_or_404(timesheet_id)
    worker = db.workers.get(ts["worker_id"])
    if worker is not None:
        check_employer_ownership(_user_id, _role, worker["employer_id"])
    if ts["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Only a SUBMITTED timesheet can be approved")
    if worker is None or worker["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Timesheet approval requires the worker to be ACTIVE")

    # No FINALIZED pay run covering this period for this worker.
    for pc in db.paychecks.values():
        if pc["worker_id"] != ts["worker_id"]:
            continue
        run = db.pay_runs.get(pc["pay_run_id"])
        if run is None or run["status"] != "FINALIZED":
            continue
        if run["period_start"] <= ts["period_start"] and run["period_end"] >= ts["period_end"]:
            raise_err(ERR_INVALID_STATE, "A FINALIZED pay run already covers this period")

    ts["status"] = "APPROVED"
    db.touch(ts)

    # Cascade: CALCULATED pay runs covering the period flip to STALE; their
    # CALCULATED paychecks get basis_stale = true. (Worker YTD/leave fields
    # are derived fresh on read, so they reflect the approval immediately.)
    for run in db.pay_runs.values():
        if run["employer_id"] != worker["employer_id"]:
            continue
        if run["status"] != "CALCULATED":
            continue
        if not (run["period_start"] <= ts["period_start"] and run["period_end"] >= ts["period_end"]):
            continue
        run["recalc_status"] = "STALE"
        db.touch(run)
        for pc in db.paychecks.values():
            if pc["pay_run_id"] == run["id"] and pc["status"] == "CALCULATED":
                pc["basis_stale"] = True
                db.touch(pc)
    return success_object(serialize_timesheet(ts))


@bp.route("/household-payroll/timesheets/<timesheet_id>/reject", methods=["POST"])
@require_roles("HouseholdClient")
def reject_timesheet(timesheet_id: str, _user_id: str, _role: str):
    ts = get_timesheet_or_404(timesheet_id)
    worker = db.workers.get(ts["worker_id"])
    if worker is not None:
        check_employer_ownership(_user_id, _role, worker["employer_id"])
    if ts["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Only a SUBMITTED timesheet can be rejected")
    ts["status"] = "DRAFT"
    db.touch(ts)
    return success_object(serialize_timesheet(ts))


@bp.route("/household-payroll/timesheets/<timesheet_id>", methods=["GET"])
@require_roles("PayrollAdmin", "HouseholdClient", "Worker")
def get_timesheet(timesheet_id: str, _user_id: str, _role: str):
    ts = get_timesheet_or_404(timesheet_id)
    _check_read_access(ts, _user_id, _role)
    return success_object(serialize_timesheet(ts))


@bp.route("/household-payroll/workers/<worker_id>/timesheets", methods=["GET"])
@require_roles("PayrollAdmin", "HouseholdClient", "Worker")
def list_timesheets(worker_id: str, _user_id: str, _role: str):
    worker = get_worker_or_404(worker_id)
    check_employer_ownership(_user_id, _role, worker["employer_id"])
    if _role == "Worker" and _user_id != worker_id:
        from middleware import forbid

        forbid("Worker may only list their own timesheets")
    limit, offset = parse_pagination()
    items = [t for t in db.timesheets.values() if t["worker_id"] == worker_id]
    items = sort_by_created_at(items)
    items = apply_filters(items, ["status"])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_timesheet(t) for t in page], limit, offset, total)
