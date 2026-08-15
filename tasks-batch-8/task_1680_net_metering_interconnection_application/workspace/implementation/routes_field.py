"""Field work: meter exchanges and inspections (PRD 3.7)."""

import datetime

import clock as clockmod
import envelope
import serializers as ser
import services
from errors import ApiError
from flask import Blueprint
from middleware import (begin, must_exist, must_ref, opt_string, paginate,
                        pagination, req_enum, req_instant, req_string)
from store import db, stamp_new, sorted_rows, touch

bp = Blueprint("field", __name__)

INSPECTION_OUTCOMES = ("PASSED", "FAILED")


def own_application(ctx, application):
    account = services.account_of(application)
    if account is None or account["customer_id"] != ctx.user_id:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")


def _check_crew_buffer(crew_id, window_start, window_end, exclude_id=None):
    """The half-open buffered interval [start - 30m, end + 30m) must not
    intersect another SCHEDULED exchange of the same crew (PRD 3.7)."""
    buffer = datetime.timedelta(minutes=services.CREW_BUFFER_MINUTES)
    new_lo = window_start - buffer
    new_hi = window_end + buffer
    for other in db.exchanges.values():
        if other["id"] == exclude_id:
            continue
        if other["crew_id"] != crew_id or other["exchange_status"] != "SCHEDULED":
            continue
        other_lo = other["_window_start"] - buffer
        other_hi = other["_window_end"] + buffer
        if new_lo < other_hi and other_lo < new_hi:
            raise ApiError("ERR_EXCHANGE_WINDOW_OVERLAP")


# ---------------------------------------------------------------------------
# Meter exchanges (PRD 3.7)
# ---------------------------------------------------------------------------

@bp.route("/meter-exchanges", methods=["POST"])
def create_exchange():
    ctx = begin("MeterTechnician")
    body = ctx.body
    application_id = req_string(body, "application_id")
    crew_id = req_string(body, "crew_id")
    window_start_dt, window_start = req_instant(body, "window_start")
    window_end_dt, window_end = req_instant(body, "window_end")
    application = must_ref(db.applications, application_id)
    if application["application_status"] != "SCREEN_PASSED":
        raise ApiError("ERR_INVALID_STATE")
    if window_end_dt <= window_start_dt:
        raise ApiError("ERR_EXCHANGE_WINDOW_INVALID")
    for other in db.exchanges.values():
        if other["application_id"] == application_id and other["exchange_status"] == "SCHEDULED":
            raise ApiError("ERR_EXCHANGE_ALREADY_ACTIVE")
    _check_crew_buffer(crew_id, window_start_dt, window_end_dt)
    row = stamp_new({
        "application_id": application_id,
        "crew_id": crew_id,
        "window_start": window_start,
        "window_end": window_end,
        "_window_start": window_start_dt,
        "_window_end": window_end_dt,
        "exchange_status": "SCHEDULED",
        "installed_meter_serial": None,
        "technician_user_id": None,
        "fail_reason": None,
    })
    db.exchanges[row["id"]] = row
    return envelope.created(ser.meter_exchange(row))


@bp.route("/meter-exchanges", methods=["GET"])
def list_exchanges():
    ctx = begin()
    rows = list(db.exchanges.values())
    application_id = ctx.query.get("application_id")
    if application_id is not None:
        rows = [r for r in rows if r["application_id"] == application_id]
    crew_id = ctx.query.get("crew_id")
    if crew_id is not None:
        rows = [r for r in rows if r["crew_id"] == crew_id]
    exchange_status = ctx.query.get("exchange_status")
    if exchange_status is not None:
        rows = [r for r in rows if r["exchange_status"] == exchange_status]
    rows = sorted_rows(rows)
    limit, offset = pagination(ctx.query)
    page, total = paginate(rows, limit, offset)
    return envelope.listing([ser.meter_exchange(r) for r in page], limit, offset, total)


@bp.route("/meter-exchanges/<meter_exchange_id>", methods=["GET"])
def get_exchange(meter_exchange_id):
    begin()
    row = must_exist(db.exchanges, meter_exchange_id)
    return envelope.ok(ser.meter_exchange(row))


@bp.route("/meter-exchanges/<meter_exchange_id>/complete", methods=["POST"])
def complete_exchange(meter_exchange_id):
    ctx = begin("MeterTechnician")
    row = must_exist(db.exchanges, meter_exchange_id)
    installed_meter_serial = req_string(ctx.body, "installed_meter_serial")
    if row["exchange_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    row["exchange_status"] = "COMPLETED"
    row["installed_meter_serial"] = installed_meter_serial
    row["technician_user_id"] = ctx.user_id
    touch(row)
    application = db.applications.get(row["application_id"])
    if application is not None:
        account = services.account_of(application)
        if account is not None:
            account["meter_serial"] = installed_meter_serial
            touch(account)
    return envelope.ok(ser.meter_exchange(row))


@bp.route("/meter-exchanges/<meter_exchange_id>/fail", methods=["POST"])
def fail_exchange(meter_exchange_id):
    ctx = begin("MeterTechnician")
    row = must_exist(db.exchanges, meter_exchange_id)
    fail_reason = req_string(ctx.body, "fail_reason")
    if row["exchange_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    row["exchange_status"] = "FAILED"
    row["fail_reason"] = fail_reason
    touch(row)
    return envelope.ok(ser.meter_exchange(row))


@bp.route("/meter-exchanges/<meter_exchange_id>/reschedule", methods=["POST"])
def reschedule_exchange(meter_exchange_id):
    ctx = begin("MeterTechnician")
    row = must_exist(db.exchanges, meter_exchange_id)
    window_start_dt, window_start = req_instant(ctx.body, "window_start")
    window_end_dt, window_end = req_instant(ctx.body, "window_end")
    if row["exchange_status"] != "FAILED":
        raise ApiError("ERR_INVALID_STATE")
    if window_end_dt <= window_start_dt:
        raise ApiError("ERR_EXCHANGE_WINDOW_INVALID")
    _check_crew_buffer(row["crew_id"], window_start_dt, window_end_dt, exclude_id=row["id"])
    row["exchange_status"] = "SCHEDULED"
    row["window_start"] = window_start
    row["window_end"] = window_end
    row["_window_start"] = window_start_dt
    row["_window_end"] = window_end_dt
    row["fail_reason"] = None
    touch(row)
    return envelope.ok(ser.meter_exchange(row))


@bp.route("/meter-exchanges/<meter_exchange_id>/cancel", methods=["POST"])
def cancel_exchange(meter_exchange_id):
    begin("MeterTechnician")
    row = must_exist(db.exchanges, meter_exchange_id)
    if row["exchange_status"] not in ("SCHEDULED", "FAILED"):
        raise ApiError("ERR_INVALID_STATE")
    row["exchange_status"] = "CANCELLED"
    touch(row)
    return envelope.ok(ser.meter_exchange(row))


# ---------------------------------------------------------------------------
# Inspections (PRD 3.7)
# ---------------------------------------------------------------------------

@bp.route("/inspections", methods=["POST"])
def create_inspection():
    ctx = begin("Applicant")
    body = ctx.body
    application_id = req_string(body, "application_id")
    scheduled_dt, scheduled_date = req_instant(body, "scheduled_date")
    application = must_ref(db.applications, application_id)
    own_application(ctx, application)
    if application["application_status"] != "SCREEN_PASSED":
        raise ApiError("ERR_INVALID_STATE")
    # The scheduled instant must not be earlier than the current clock time
    # (PRD 3.7).
    if scheduled_dt < clockmod.now():
        raise ApiError("ERR_INSPECTION_DATE_INVALID")
    for other in db.inspections.values():
        if other["application_id"] == application_id and other["inspection_status"] == "SCHEDULED":
            raise ApiError("ERR_INSPECTION_EXISTS")
    completed = any(
        e["application_id"] == application_id and e["exchange_status"] == "COMPLETED"
        for e in db.exchanges.values()
    )
    if not completed:
        raise ApiError("ERR_METER_EXCHANGE_NOT_COMPLETED")
    row = stamp_new({
        "application_id": application_id,
        "scheduled_date": scheduled_date,
        "_scheduled_date": scheduled_dt,
        "inspection_status": "SCHEDULED",
        "outcome": None,
        "occurred_at": None,
        "_occurred_at": None,
        "defects": None,
        "inspector_user_id": None,
    })
    db.inspections[row["id"]] = row
    return envelope.created(ser.inspection(row))


@bp.route("/inspections", methods=["GET"])
def list_inspections():
    ctx = begin()
    rows = list(db.inspections.values())
    application_id = ctx.query.get("application_id")
    if application_id is not None:
        rows = [r for r in rows if r["application_id"] == application_id]
    inspection_status = ctx.query.get("inspection_status")
    if inspection_status is not None:
        rows = [r for r in rows if r["inspection_status"] == inspection_status]
    rows = sorted_rows(rows)
    limit, offset = pagination(ctx.query)
    page, total = paginate(rows, limit, offset)
    return envelope.listing([ser.inspection(r) for r in page], limit, offset, total)


@bp.route("/inspections/<inspection_id>", methods=["GET"])
def get_inspection(inspection_id):
    begin()
    row = must_exist(db.inspections, inspection_id)
    return envelope.ok(ser.inspection(row))


@bp.route("/inspections/<inspection_id>/record-result", methods=["POST"])
def record_inspection_result(inspection_id):
    ctx = begin("Inspector")
    row = must_exist(db.inspections, inspection_id)
    body = ctx.body
    outcome = req_enum(body, "outcome", INSPECTION_OUTCOMES)
    occurred_dt, occurred_at = req_instant(body, "occurred_at")
    defects = opt_string(body, "defects")
    if row["inspection_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    # Segregation of duties (rung 9): the inspector must not be the technician
    # who completed this application's meter exchange.
    application = db.applications.get(row["application_id"])
    if application is not None:
        completed = [
            e for e in db.exchanges.values()
            if e["application_id"] == application["id"] and e["exchange_status"] == "COMPLETED"
        ]
        completed.sort(key=lambda e: (e["created_at"], e["_seq"]))
        if completed and completed[-1]["technician_user_id"] == ctx.user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if occurred_dt < row["_scheduled_date"] or occurred_dt > clockmod.now():
        raise ApiError("ERR_INSPECTION_DATE_INVALID")
    if (outcome == "FAILED") != (defects is not None and defects != ""):
        raise ApiError("ERR_DEFECTS_REQUIRED")
    row["inspection_status"] = "RESULT_RECORDED"
    row["outcome"] = outcome
    row["occurred_at"] = occurred_at
    row["_occurred_at"] = occurred_dt
    row["defects"] = defects if outcome == "FAILED" else None
    row["inspector_user_id"] = ctx.user_id
    touch(row)
    return envelope.ok(ser.inspection(row))


@bp.route("/inspections/<inspection_id>/cancel", methods=["POST"])
def cancel_inspection(inspection_id):
    ctx = begin("Applicant")
    row = must_exist(db.inspections, inspection_id)
    application = db.applications.get(row["application_id"])
    if application is not None:
        own_application(ctx, application)
    if row["inspection_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    row["inspection_status"] = "CANCELLED"
    touch(row)
    return envelope.ok(ser.inspection(row))
