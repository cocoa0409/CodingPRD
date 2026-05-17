"""Appointment routes."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from flask import Blueprint, request

from ..auth import require_roles
from ..clock import now
from ..errors import (
    err_appt_not_open,
    err_forbidden,
    err_invalid_state,
    err_invalid_timerange,
    err_license_gap_for_state,
    err_not_found,
    err_outside_checkin_window,
    err_patient_double_booked,
    err_reference_not_found,
    err_safety_plan_required,
    err_session_not_open,
    err_therapist_double_booked,
    err_therapist_not_active,
    err_no_active_supervisor,
    err_validation,
)
from ..helpers import (
    assert_enum,
    assert_integer,
    assert_string,
    new_uuid,
    occ_check,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing, ok
from ..services.calculations import is_psypact_state
from ..services.cascades import bump
from ..services.serialize import serialize_appointment, serialize_session
from ..store import store

bp = Blueprint("appointments", __name__, url_prefix="/practice/appointments")

CPT_CODES = ["90791", "90834"]
MODALITIES = ["IN_PERSON", "TELEHEALTH"]
APPT_STATUSES = ["SCHEDULED", "HELD", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED"]
APPT_NON_TERMINAL = {"SCHEDULED", "HELD", "CHECKED_IN"}


# ---------------- Collision helpers ------------------------------------------

def _therapist_overlap_violation(s, *, therapist_id: str, start, end, exclude_id: str | None) -> bool:
    for a in s.appointments.values():
        if a["id"] == exclude_id:
            continue
        if a["therapist_id"] != therapist_id:
            continue
        if a["status"] not in APPT_NON_TERMINAL:
            continue
        # Half-open [start, end) overlap.
        if a["scheduled_start"] < end and start < a["scheduled_end"]:
            return True
    return False


def _patient_gap_violation(s, *, patient_id: str, start, end, exclude_id: str | None) -> bool:
    five = timedelta(minutes=5)
    for a in s.appointments.values():
        if a["id"] == exclude_id:
            continue
        if a["patient_id"] != patient_id:
            continue
        if a["status"] not in APPT_NON_TERMINAL:
            continue
        # Need at least 5 min gap on either side; otherwise violation.
        if not (start - a["scheduled_end"] >= five or a["scheduled_start"] - end >= five):
            return True
    return False


# ---------------- Create ------------------------------------------------------

@bp.post("")
@require_roles("PracticeAdmin", "Therapist")
def create_appointment(_caller_id: str, _caller_role: str, **_):
    body = require_json_object()
    therapist_id = assert_string(body.get("therapist_id"), "therapist_id")
    patient_id = assert_string(body.get("patient_id"), "patient_id")
    cpt_code = assert_enum(body.get("cpt_code"), "cpt_code", CPT_CODES)
    modality = assert_enum(body.get("modality"), "modality", MODALITIES)
    patient_state_on_day = assert_string(body.get("patient_state_on_day"), "patient_state_on_day", pattern=r"^[A-Z]{2}$")
    scheduled_start = parse_iso8601(body.get("scheduled_start"), "scheduled_start")
    scheduled_end = parse_iso8601(body.get("scheduled_end"), "scheduled_end")

    s = store()
    with s.lock:
        if therapist_id not in s.therapists:
            raise err_reference_not_found("therapist_id does not resolve")
        if patient_id not in s.patients:
            raise err_reference_not_found("patient_id does not resolve")

        # Therapist role ownership for create
        if _caller_role == "Therapist" and _caller_id != therapist_id:
            raise err_forbidden("Therapist may only schedule for themselves")

        if scheduled_end <= scheduled_start or (scheduled_end - scheduled_start) < timedelta(minutes=1):
            raise err_invalid_timerange("scheduled_end must be at least 1 minute after scheduled_start")

        if _therapist_overlap_violation(s, therapist_id=therapist_id, start=scheduled_start, end=scheduled_end, exclude_id=None):
            raise err_therapist_double_booked()
        if _patient_gap_violation(s, patient_id=patient_id, start=scheduled_start, end=scheduled_end, exclude_id=None):
            raise err_patient_double_booked()

        aid = new_uuid()
        ts = now()
        row: dict[str, Any] = {
            "id": aid,
            "therapist_id": therapist_id,
            "patient_id": patient_id,
            "cpt_code": cpt_code,
            "modality": modality,
            "patient_state_on_day": patient_state_on_day,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "status": "SCHEDULED",
            "hold_reason": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        s.appointments[aid] = row
        return created(serialize_appointment(row))


# ---------------- Read --------------------------------------------------------

@bp.get("/<aid>")
@require_roles("PracticeAdmin", "Therapist", "BillingClerk")
def get_appointment(aid: str, **_):
    s = store()
    row = s.appointments.get(aid)
    if row is None:
        raise err_not_found("Appointment not found")
    return ok(serialize_appointment(row))


# ---------------- List --------------------------------------------------------

@bp.get("")
@require_roles("PracticeAdmin", "Therapist", "BillingClerk")
def list_appointments(**_):
    limit, offset = parse_pagination()
    therapist_id = request.args.get("therapist_id")
    patient_id = request.args.get("patient_id")
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in APPT_STATUSES:
        raise err_validation("status filter invalid")
    s = store()
    rows = list(s.appointments.values())
    if therapist_id:
        rows = [r for r in rows if r["therapist_id"] == therapist_id]
    if patient_id:
        rows = [r for r in rows if r["patient_id"] == patient_id]
    if status_filter:
        rows = [r for r in rows if r["status"] == status_filter]
    rows.sort(key=lambda r: r["created_at"])
    return listing([serialize_appointment(r) for r in paginate(rows, limit, offset)],
                   total_count=len(rows), limit=limit, offset=offset)


# ---------------- PATCH -------------------------------------------------------

@bp.patch("/<aid>")
@require_roles("PracticeAdmin", "Therapist")
def update_appointment(aid: str, _caller_id: str, _caller_role: str, **_):
    body = require_json_object()
    s = store()
    with s.lock:
        row = s.appointments.get(aid)
        if row is None:
            raise err_not_found("Appointment not found")
        if _caller_role == "Therapist" and _caller_id != row["therapist_id"]:
            raise err_forbidden("Therapist may only update their own appointments")
        occ_check(body.get("version"), row["version"])
        if row["status"] not in {"SCHEDULED", "HELD"}:
            raise err_invalid_state("Appointment may only be patched while SCHEDULED or HELD")

        new_start = row["scheduled_start"]
        new_end = row["scheduled_end"]
        if "scheduled_start" in body:
            new_start = parse_iso8601(body["scheduled_start"], "scheduled_start")
        if "scheduled_end" in body:
            new_end = parse_iso8601(body["scheduled_end"], "scheduled_end")
        if "modality" in body:
            row["modality"] = assert_enum(body["modality"], "modality", MODALITIES)
        if "patient_state_on_day" in body:
            row["patient_state_on_day"] = assert_string(
                body["patient_state_on_day"], "patient_state_on_day", pattern=r"^[A-Z]{2}$"
            )

        if "scheduled_start" in body or "scheduled_end" in body:
            if new_end <= new_start or (new_end - new_start) < timedelta(minutes=1):
                raise err_invalid_timerange("scheduled_end must be at least 1 minute after scheduled_start")
            if _therapist_overlap_violation(s, therapist_id=row["therapist_id"], start=new_start, end=new_end, exclude_id=aid):
                raise err_therapist_double_booked()
            if _patient_gap_violation(s, patient_id=row["patient_id"], start=new_start, end=new_end, exclude_id=aid):
                raise err_patient_double_booked()
            row["scheduled_start"] = new_start
            row["scheduled_end"] = new_end

        bump(row)
        return ok(serialize_appointment(row))


# ---------------- Check-in ----------------------------------------------------

def _therapist_has_active_assignment(s, tid: str) -> bool:
    return any(a["therapist_id"] == tid and a["status"] == "ACTIVE"
               for a in s.supervision_assignments.values())


def _coverage_for_state(s, therapist_id: str, state_code: str) -> bool:
    therapist = s.therapists.get(therapist_id)
    if therapist is None:
        return False
    active_licenses = [l for l in s.state_licenses.values()
                       if l["therapist_id"] == therapist_id and l["status"] == "ACTIVE"]
    if any(l["state_code"] == state_code for l in active_licenses):
        return True
    if therapist.get("psypact_enrolled") and is_psypact_state(state_code):
        if any(is_psypact_state(l["state_code"]) for l in active_licenses):
            return True
    return False


@bp.post("/<aid>/check-in")
@require_roles("Therapist", "PracticeAdmin")
def check_in(aid: str, _caller_id: str, _caller_role: str, **_):
    body = require_json_object()
    s = store()
    with s.lock:
        appt = s.appointments.get(aid)
        if appt is None:
            raise err_not_found("Appointment not found")
        # State must be SCHEDULED — anything else → ERR_APPT_NOT_OPEN.
        if appt["status"] != "SCHEDULED":
            raise err_appt_not_open()
        occ_check(body.get("version"), appt["version"])

        # Ownership: Therapist must own this appointment.
        if _caller_role == "Therapist" and _caller_id != appt["therapist_id"]:
            raise err_forbidden("Therapist may only check in their own appointments")

        therapist = s.therapists[appt["therapist_id"]]
        patient = s.patients[appt["patient_id"]]

        # §2.7 ordering: safety first.
        if patient["safety_plan_required"]:
            raise err_safety_plan_required()

        # Therapist credential status must be PROVISIONAL or ACTIVE.
        if therapist["credential_status"] not in {"PROVISIONAL", "ACTIVE"}:
            raise err_therapist_not_active()

        # License coverage check.
        if not _coverage_for_state(s, therapist["id"], appt["patient_state_on_day"]):
            raise err_license_gap_for_state()

        # Check-in window: [start - 15m, start + 30m].
        current = now()
        from datetime import timedelta as _td
        if current < appt["scheduled_start"] - _td(minutes=15) or current > appt["scheduled_start"] + _td(minutes=30):
            raise err_outside_checkin_window()

        # PRE_LICENSED: requires active supervision assignment.
        if therapist["supervision_track"] == "PRE_LICENSED":
            if not _therapist_has_active_assignment(s, therapist["id"]):
                raise err_no_active_supervisor()

        appt["status"] = "CHECKED_IN"
        bump(appt)
        return ok(serialize_appointment(appt))


# ---------------- Cancel ------------------------------------------------------

@bp.post("/<aid>/cancel")
@require_roles("Therapist", "PracticeAdmin")
def cancel(aid: str, _caller_id: str, _caller_role: str, **_):
    body = require_json_object()
    s = store()
    with s.lock:
        appt = s.appointments.get(aid)
        if appt is None:
            raise err_not_found("Appointment not found")
        occ_check(body.get("version"), appt["version"])
        if _caller_role == "Therapist" and _caller_id != appt["therapist_id"]:
            raise err_forbidden("Therapist may only cancel their own appointments")
        if appt["status"] not in {"SCHEDULED", "HELD"}:
            raise err_appt_not_open()
        # Must be strictly before scheduled_start.
        if now() >= appt["scheduled_start"]:
            raise err_appt_not_open()
        appt["status"] = "CANCELLED"
        appt["hold_reason"] = None
        bump(appt)
        return ok(serialize_appointment(appt))


# ---------------- Mark no-show ------------------------------------------------

@bp.post("/<aid>/mark-no-show")
@require_roles("Therapist", "PracticeAdmin")
def mark_no_show(aid: str, _caller_id: str, _caller_role: str, **_):
    body = require_json_object()
    s = store()
    with s.lock:
        appt = s.appointments.get(aid)
        if appt is None:
            raise err_not_found("Appointment not found")
        occ_check(body.get("version"), appt["version"])
        if _caller_role == "Therapist" and _caller_id != appt["therapist_id"]:
            raise err_forbidden("Therapist may only mark-no-show on their own appointments")
        if appt["status"] != "SCHEDULED":
            raise err_appt_not_open()
        if now() <= appt["scheduled_end"]:
            raise err_appt_not_open()
        appt["status"] = "NO_SHOW"
        bump(appt)
        return ok(serialize_appointment(appt))


# ---------------- Open Session under appointment ------------------------------

@bp.post("/<aid>/sessions")
@require_roles("Therapist")
def open_session(aid: str, _caller_id: str, _caller_role: str, **_):
    body = require_json_object()
    s = store()
    with s.lock:
        appt = s.appointments.get(aid)
        if appt is None:
            raise err_not_found("Appointment not found")
        if _caller_id != appt["therapist_id"]:
            raise err_forbidden("Therapist may only open sessions for their own appointments")
        if appt["status"] != "CHECKED_IN":
            raise err_session_not_open()
        duration = assert_integer(body.get("actual_duration_minutes"), "actual_duration_minutes", minimum=1)
        sid = new_uuid()
        ts = now()
        sess: dict[str, Any] = {
            "id": sid,
            "appointment_id": aid,
            "type": "INTAKE" if appt["cpt_code"] == "90791" else "INDIVIDUAL",
            "actual_duration_minutes": duration,
            "supervision_credit_hours": Decimal("0.00"),
            "status": "IN_PROGRESS",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        s.sessions[sid] = sess
        return created(serialize_session(sess))
