from datetime import timedelta
from flask import Blueprint, request

from db import store
from middleware import authenticate, require_roles
from common import (
    get_json_body, require_string, require_enum, get_or_404, make_entity, touch,
    parse_pagination, paginate,
)
from clock import parse_datetime, now
from response import success, success_list
from errors import (
    err, ERR_FORBIDDEN, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_INVALID_STATE, ERR_APPOINTMENT_NOT_STARTED, ERR_APPOINTMENT_OVERLAP,
)
from services.billing import append_billing_entry
from services.calculations import (
    compute_billed_minutes, compute_appointment_amount,
)

bp = Blueprint("appointments", __name__)

APPOINTMENT_BUFFER_MIN = 15


def serialize(a):
    return {
        "id": a["id"],
        "student_id": a["student_id"],
        "counselor_id": a["counselor_id"],
        "start_utc": a["start_utc"],
        "end_utc": a["end_utc"],
        "meeting_type": a["meeting_type"],
        "status": a["status"],
        "billed_minutes": a["billed_minutes"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.route("/appointments", methods=["POST"])
def create_appointment():
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    body = get_json_body()
    student_id = require_string(body, "student_id")
    start_raw = require_string(body, "start_utc")
    end_raw = require_string(body, "end_utc")
    meeting_type = require_enum(body, "meeting_type", {"STRATEGY", "ESSAY_REVIEW", "CHECK_IN"})
    start_dt = parse_datetime(start_raw)
    end_dt = parse_datetime(end_raw)
    if not (end_dt > start_dt):
        raise err(ERR_INVALID_REQUEST, "end_utc must be strictly after start_utc")

    with store.lock:
        student = store.students.get(student_id)
        if student is None:
            raise err(ERR_REFERENCE_NOT_FOUND, "student_id does not reference an existing student")
        counselor_id = student["counselor_id"]
        if counselor_id != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor does not own this student")

        # buffered overlap check on the counselor's calendar (half-open + buffer)
        buffer = timedelta(minutes=APPOINTMENT_BUFFER_MIN)
        new_lo = start_dt - buffer
        new_hi = end_dt + buffer
        for other in store.appointments.values():
            if other.get("counselor_id") != counselor_id:
                continue
            if other.get("status") not in ("BOOKED", "COMPLETED"):
                continue
            o_start = parse_datetime(other["start_utc"])
            o_end = parse_datetime(other["end_utc"])
            if new_lo < o_end and o_start < new_hi:
                raise err(ERR_APPOINTMENT_OVERLAP, "Appointment overlaps an existing one")

        a = make_entity()
        a.update({
            "student_id": student_id,
            "counselor_id": counselor_id,
            "start_utc": start_raw,
            "end_utc": end_raw,
            "meeting_type": meeting_type,
            "status": "BOOKED",
            "billed_minutes": 0,
        })
        store.appointments[a["id"]] = a
        return success(serialize(a), 201)


@bp.route("/appointments/<appointment_id>", methods=["GET"])
def get_appointment(appointment_id):
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    with store.lock:
        a = get_or_404(store.appointments, appointment_id)
        _assert_access(caller, a)
        return success(serialize(a))


@bp.route("/appointments", methods=["GET"])
def list_appointments():
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    limit, offset = parse_pagination()
    filt_student = request.args.get("student_id")
    filt_counselor = request.args.get("counselor_id")
    filt_status = request.args.get("status")
    with store.lock:
        rows = [r for r in store.appointments.values() if _visible(caller, r)]
        if filt_student is not None:
            rows = [r for r in rows if r.get("student_id") == filt_student]
        if filt_counselor is not None:
            rows = [r for r in rows if r.get("counselor_id") == filt_counselor]
        if filt_status is not None:
            rows = [r for r in rows if r.get("status") == filt_status]
        page, total = paginate(rows, limit, offset)
        return success_list([serialize(r) for r in page], limit, offset, total)


@bp.route("/appointments/<appointment_id>/complete", methods=["POST"])
def complete_appointment(appointment_id):
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    with store.lock:
        a = get_or_404(store.appointments, appointment_id)
        if a.get("counselor_id") != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor does not own this appointment")
        if a["status"] != "BOOKED":
            raise err(ERR_INVALID_STATE, "Appointment is not BOOKED")
        start_dt = parse_datetime(a["start_utc"])
        if not (now() >= start_dt):
            raise err(ERR_APPOINTMENT_NOT_STARTED, "Appointment has not started")

        end_dt = parse_datetime(a["end_utc"])
        billed_minutes = compute_billed_minutes(start_dt, end_dt)
        a["billed_minutes"] = billed_minutes
        a["status"] = "COMPLETED"

        # HOURLY billing
        contract = _active_hourly_contract(a["student_id"])
        if contract is not None:
            amount = compute_appointment_amount(billed_minutes, contract["hourly_rate_cents"])
            append_billing_entry(
                contract=contract,
                entry_type="CHARGE",
                source_kind="APPOINTMENT",
                amount_cents=amount,
                source_id=a["id"],
                minutes=billed_minutes,
                memo="",
                recompute=True,
            )
        touch(a)
        return success(serialize(a))


@bp.route("/appointments/<appointment_id>/cancel", methods=["POST"])
def cancel_appointment(appointment_id):
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    with store.lock:
        a = get_or_404(store.appointments, appointment_id)
        if a.get("counselor_id") != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor does not own this appointment")
        if a["status"] != "BOOKED":
            raise err(ERR_INVALID_STATE, "Appointment is not BOOKED")
        a["status"] = "CANCELLED"
        touch(a)
        return success(serialize(a))


def _active_hourly_contract(student_id):
    for c in store.contracts.values():
        if (c.get("student_id") == student_id and c.get("status") == "ACTIVE"
                and c.get("billing_model") == "HOURLY"):
            return c
    return None


def _visible(caller, a):
    if caller.is_counselor:
        return a.get("counselor_id") == caller.user_id
    if caller.is_student:
        return a.get("student_id") == caller.user_id
    return False


def _assert_access(caller, a):
    if not _visible(caller, a):
        raise err(ERR_FORBIDDEN, "Not permitted on this appointment")
