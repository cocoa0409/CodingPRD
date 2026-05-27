"""Biometrics endpoints: schedule, list, get, complete, reschedule, no-show."""
from __future__ import annotations

from datetime import timedelta
from typing import Optional, List

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL,
    ERR_CASE_TYPE_NOT_APPLICABLE,
    ERR_APPT_TOO_SOON,
    ERR_APPT_OVERLAP_SAME_CASE,
    ERR_ASC_SLOT_TAKEN,
)
from middleware import require_auth, get_json_body, current_role, current_user_id
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import (
    require_fields,
    require_string,
    lookup_or_404,
    ensure_case_ownership,
    parse_appt_dt,
    parse_clock_dt,
)
from services.events import append_event
from services.calculations import TERMINAL_CASE_STATES


bp = Blueprint("biometrics", __name__)


ALL_ROLES = ["Applicant", "Attorney", "Officer", "FieldOfficeAdmin"]
APPT_DURATION_MIN = 60
SEVEN_DAYS = timedelta(days=7)
GRACE_24H = timedelta(hours=24)


def _check_overlap_same_case(case_id: str, new_dt) -> None:
    """Half-open [start, start+60min) overlap rule, per-case."""
    new_start = new_dt
    new_end = new_dt + timedelta(minutes=APPT_DURATION_MIN)
    for a in db.biometrics.values():
        if a.get("case_id") != case_id:
            continue
        if a.get("status") != "SCHEDULED":
            continue
        existing_start = db.parse_iso_dt(a.get("scheduled_at"))
        if existing_start is None:
            continue
        existing_end = existing_start + timedelta(minutes=APPT_DURATION_MIN)
        # Geometric overlap of [a, b) and [c, d) iff a < d and c < b.
        if new_start < existing_end and existing_start < new_end:
            raise APIError(ERR_APPT_OVERLAP_SAME_CASE, 409, "Biometrics appointment overlaps existing one for this case")


def _check_asc_slot(asc_code: str, new_dt) -> None:
    """Point-instant capacity at the ASC location — same scheduled_at instant collides."""
    for a in db.biometrics.values():
        if a.get("asc_location_code") != asc_code:
            continue
        if a.get("status") != "SCHEDULED":
            continue
        existing = db.parse_iso_dt(a.get("scheduled_at"))
        if existing is None:
            continue
        if existing == new_dt:
            raise APIError(ERR_ASC_SLOT_TAKEN, 409, "ASC location already has an appointment at this instant")


# ---------- POST /uscis/cases/{id}/biometrics --------------------------------

@bp.post("/uscis/cases/<rid>/biometrics")
def schedule_biometrics(rid: str):
    require_auth(["Officer"])()
    case = lookup_or_404(db.cases, rid, "Case")

    if case.get("status") in TERMINAL_CASE_STATES:
        raise APIError(ERR_ALREADY_TERMINAL, 409, "Case is already terminal")
    if case.get("status") != "FILED":
        raise APIError(ERR_INVALID_STATE, 409, f"Case must be in FILED (was {case.get('status')})")
    if case.get("case_type") == "I-130":
        raise APIError(ERR_CASE_TYPE_NOT_APPLICABLE, 422, "Biometrics do not apply to I-130")

    body = get_json_body()
    require_fields(body, ["scheduled_at", "asc_location_code"])
    scheduled_at = body["scheduled_at"]
    asc_code = body["asc_location_code"]
    require_string(asc_code, "asc_location_code")

    new_dt = parse_appt_dt(scheduled_at, "scheduled_at")
    now_dt = parse_clock_dt()

    # Priority: 12 ERR_APPT_TOO_SOON, 13 ERR_APPT_OVERLAP_SAME_CASE, 14 ERR_ASC_SLOT_TAKEN.
    if new_dt < now_dt + SEVEN_DAYS:
        raise APIError(ERR_APPT_TOO_SOON, 422, "Appointment must be at least 7 days in the future")
    _check_overlap_same_case(case["id"], new_dt)
    _check_asc_slot(asc_code, new_dt)

    appt = {
        "case_id": case["id"],
        "scheduled_at": scheduled_at,
        "asc_location_code": asc_code,
        "status": "SCHEDULED",
    }
    db.stamp_common(appt)
    db.biometrics[appt["id"]] = appt

    prior = case["status"]
    case["status"] = "BIOMETRICS_SCHEDULED"
    db.bump(case)
    append_event(case["id"], "STATUS_CHANGE", from_status=prior, to_status="BIOMETRICS_SCHEDULED")
    return ok_object(appt, 201)


# ---------- GET /uscis/cases/{id}/biometrics --------------------------------

@bp.get("/uscis/cases/<rid>/biometrics")
def list_case_biometrics(rid: str):
    require_auth(ALL_ROLES)()
    case = lookup_or_404(db.cases, rid, "Case")
    ensure_case_ownership(case, current_role(), current_user_id())
    limit, offset = paginate_params(request.args)
    items = [a for a in db.biometrics.values() if a.get("case_id") == rid]
    items.sort(key=lambda a: a.get("created_at", ""))
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


# ---------- GET /uscis/biometrics/{id} --------------------------------------

@bp.get("/uscis/biometrics/<rid>")
def get_biometrics(rid: str):
    require_auth(ALL_ROLES)()
    appt = lookup_or_404(db.biometrics, rid, "BiometricsAppointment")
    return ok_object(appt, 200)


# ---------- POST /uscis/biometrics/{id}/complete ----------------------------

@bp.post("/uscis/biometrics/<rid>/complete")
def complete_biometrics(rid: str):
    require_auth(["Officer"])()
    appt = lookup_or_404(db.biometrics, rid, "BiometricsAppointment")

    if appt.get("status") in ("COMPLETED", "NO_SHOW"):
        raise APIError(ERR_ALREADY_TERMINAL, 409, "Appointment already terminal")
    if appt.get("status") != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409, "Appointment must be SCHEDULED")
    appt_dt = db.parse_iso_dt(appt["scheduled_at"])
    now_dt = parse_clock_dt()
    if now_dt < appt_dt:
        raise APIError(ERR_INVALID_STATE, 409, "Clock has not reached scheduled_at yet")

    case = db.cases.get(appt["case_id"])
    if case is None or case.get("status") != "BIOMETRICS_SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409, "Parent case must be in BIOMETRICS_SCHEDULED")

    appt["status"] = "COMPLETED"
    db.bump(appt)

    prior = case["status"]
    case["status"] = "BIOMETRICS_COMPLETED"
    db.bump(case)
    append_event(case["id"], "BIOMETRICS_COMPLETED", payload_json={"biometrics_id": appt["id"]})
    append_event(case["id"], "STATUS_CHANGE", from_status=prior, to_status="BIOMETRICS_COMPLETED")
    return ok_object(appt, 200)


# ---------- POST /uscis/biometrics/{id}/reschedule --------------------------

@bp.post("/uscis/biometrics/<rid>/reschedule")
def reschedule_biometrics(rid: str):
    require_auth(["Officer"])()
    appt = lookup_or_404(db.biometrics, rid, "BiometricsAppointment")

    if appt.get("status") in ("COMPLETED", "NO_SHOW", "RESCHEDULED"):
        raise APIError(ERR_ALREADY_TERMINAL, 409, "Appointment already terminal")
    if appt.get("status") != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409, "Appointment must be SCHEDULED")

    body = get_json_body()
    require_fields(body, ["new_scheduled_at", "new_asc_location_code"])
    new_scheduled_at = body["new_scheduled_at"]
    new_asc_code = body["new_asc_location_code"]
    require_string(new_asc_code, "new_asc_location_code")
    new_dt = parse_appt_dt(new_scheduled_at, "new_scheduled_at")
    now_dt = parse_clock_dt()

    if new_dt < now_dt + SEVEN_DAYS:
        raise APIError(ERR_APPT_TOO_SOON, 422, "New time must be at least 7 days in the future")

    case_id = appt["case_id"]
    # Mark current as RESCHEDULED FIRST (so the overlap check ignores it).
    old_status = appt["status"]
    old_scheduled_at = appt["scheduled_at"]
    appt["status"] = "RESCHEDULED"
    db.bump(appt)

    try:
        _check_overlap_same_case(case_id, new_dt)
        _check_asc_slot(new_asc_code, new_dt)
    except APIError:
        # Roll back the status flip.
        appt["status"] = old_status
        # Decrement the version we just bumped to avoid leaking a phantom mutation.
        appt["version"] = max(1, appt.get("version", 1) - 1)
        raise

    new_appt = {
        "case_id": case_id,
        "scheduled_at": new_scheduled_at,
        "asc_location_code": new_asc_code,
        "status": "SCHEDULED",
    }
    db.stamp_common(new_appt)
    db.biometrics[new_appt["id"]] = new_appt

    case = db.cases.get(case_id)
    if case is not None:
        db.bump(case)
        append_event(
            case["id"],
            "STATUS_CHANGE",
            from_status="BIOMETRICS_SCHEDULED",
            to_status="BIOMETRICS_SCHEDULED",
            payload_json={"rescheduled_from": old_scheduled_at, "rescheduled_to": new_scheduled_at},
        )

    # PRD says output is the BiometricsAppointment. Return the new (active) one.
    return ok_object(new_appt, 200)


# ---------- POST /uscis/biometrics/{id}/mark-no-show ------------------------

@bp.post("/uscis/biometrics/<rid>/mark-no-show")
def mark_no_show_biometrics(rid: str):
    require_auth(["Officer"])()
    appt = lookup_or_404(db.biometrics, rid, "BiometricsAppointment")

    if appt.get("status") in ("COMPLETED", "NO_SHOW", "RESCHEDULED"):
        raise APIError(ERR_ALREADY_TERMINAL, 409, "Appointment already terminal")
    if appt.get("status") != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409, "Appointment must be SCHEDULED")

    appt_dt = db.parse_iso_dt(appt["scheduled_at"])
    now_dt = parse_clock_dt()
    if now_dt < appt_dt + GRACE_24H:
        raise APIError(ERR_INVALID_STATE, 409, "Grace window has not elapsed")

    appt["status"] = "NO_SHOW"
    db.bump(appt)

    case = db.cases.get(appt["case_id"])
    if case is not None and case.get("status") not in TERMINAL_CASE_STATES:
        prior = case["status"]
        case["status"] = "ABANDONED"
        db.bump(case)
        append_event(case["id"], "STATUS_CHANGE", from_status=prior, to_status="ABANDONED")
    return ok_object(appt, 200)
