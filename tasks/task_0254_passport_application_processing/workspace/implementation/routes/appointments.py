"""Appointments: book (two interval semantics), read, list, cancel, complete."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_ALREADY_TERMINAL,
    ERR_COUNTER_SLOT_CONFLICT,
    ERR_DUPLICATE_URGENT_APPOINTMENT,
    ERR_FACILITY_SLOT_CONFLICT,
    ERR_FK_NOT_FOUND,
    ERR_INVALID_INTERVAL,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_STALE_VERSION,
)
from middleware import require_auth
from response import ok_array, ok_object
from routes._helpers import (
    get_body,
    order_by_created,
    paginate,
    parse_pagination,
    require_enum,
    require_str,
    serialize,
    serialize_list,
    stamp_create,
    touch,
)
from services import calculations as calc
from services import domain

bp = Blueprint("appointments", __name__)

RESOURCE_KINDS = {"ACCEPTANCE_FACILITY", "URGENT_TRAVEL_COUNTER"}


def _parse_instant(iso: str, field: str) -> datetime:
    s = iso
    if isinstance(s, str) and s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field} must be an ISO 8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _appt_or_404(rid: str) -> dict:
    rec = db.appointments.get(rid)
    if rec is None:
        raise APIError(ERR_NOT_FOUND, 404, "Appointment not found")
    return rec


@bp.route("/appointments", methods=["POST"])
def book_appointment():
    require_auth(["Applicant"])
    body = get_body()

    for f in ("application_id", "resource_kind", "start_utc", "end_utc", "expected_application_version"):
        if f not in body or body.get(f) is None:
            raise APIError(ERR_INVALID_REQUEST, 400, f"Missing required field: {f}")

    application_id = require_str(body, "application_id")
    resource_kind = require_enum(body, "resource_kind", RESOURCE_KINDS)
    start_raw = require_str(body, "start_utc")
    end_raw = require_str(body, "end_utc")

    expected = body["expected_application_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise APIError(ERR_INVALID_REQUEST, 400, "expected_application_version must be an integer")

    facility_id = body.get("facility_id")
    counter_id = body.get("counter_id")

    # ---- 3/4 existence ----
    app_rec = db.applications.get(application_id)
    if app_rec is None:
        raise APIError(ERR_FK_NOT_FOUND, 422, "application_id does not exist")

    if resource_kind == "ACCEPTANCE_FACILITY":
        if facility_id is None:
            raise APIError(ERR_INVALID_REQUEST, 400, "facility_id required for ACCEPTANCE_FACILITY")
        if not isinstance(facility_id, str):
            raise APIError(ERR_INVALID_REQUEST, 400, "facility_id must be a string")
        if facility_id not in db.acceptance_facilities:
            raise APIError(ERR_FK_NOT_FOUND, 422, "facility_id does not exist")
        counter_id = None
    else:  # URGENT_TRAVEL_COUNTER
        if counter_id is None:
            raise APIError(ERR_INVALID_REQUEST, 400, "counter_id required for URGENT_TRAVEL_COUNTER")
        if not isinstance(counter_id, str):
            raise APIError(ERR_INVALID_REQUEST, 400, "counter_id must be a string")
        if counter_id not in db.urgent_travel_counters:
            raise APIError(ERR_FK_NOT_FOUND, 422, "counter_id does not exist")
        facility_id = None

    start_dt = _parse_instant(start_raw, "start_utc")
    end_dt = _parse_instant(end_raw, "end_utc")

    # ---- conflict checks (priority 11/12) come before interval validity (13),
    #      duplicate-urgent (14), then OCC (17) per PRD §2.9 ordering ----
    if resource_kind == "ACCEPTANCE_FACILITY":
        _check_facility_conflict(facility_id, start_dt, end_dt)
    else:
        _check_counter_conflict(counter_id, start_dt, end_dt)

    # 13 interval validity
    if not (end_dt > start_dt):
        raise APIError(ERR_INVALID_INTERVAL, 422, "end_utc must be strictly after start_utc")

    # 14 single urgent appointment per application
    if resource_kind == "URGENT_TRAVEL_COUNTER":
        if domain.has_booked_urgent(application_id):
            raise APIError(ERR_DUPLICATE_URGENT_APPOINTMENT, 409, "Application already holds a BOOKED urgent appointment")

    # 17 OCC
    if expected != app_rec["version"]:
        raise APIError(ERR_STALE_VERSION, 412, "expected_application_version does not match")

    appt = {
        "application_id": application_id,
        "resource_kind": resource_kind,
        "facility_id": facility_id,
        "counter_id": counter_id,
        "start_utc": start_raw,
        "end_utc": end_raw,
        "status": "BOOKED",
    }
    stamp_create(appt, full=True)
    db.appointments[appt["id"]] = appt

    # Side effects: urgent flag + fee re-derivation, then bump application version
    if resource_kind == "URGENT_TRAVEL_COUNTER":
        app_rec["urgent_travel"] = True
        domain.rederive_fee_if_unpaid(app_rec)
    touch(app_rec)

    return ok_object(serialize(appt), 201)


def _check_facility_conflict(facility_id: str, start_dt: datetime, end_dt: datetime) -> None:
    """Half-open [start, end); adjacency end==start allowed."""
    for ap in db.appointments.values():
        if ap["resource_kind"] != "ACCEPTANCE_FACILITY":
            continue
        if ap["facility_id"] != facility_id or ap["status"] != "BOOKED":
            continue
        ex_start = _parse_instant(ap["start_utc"], "start_utc")
        ex_end = _parse_instant(ap["end_utc"], "end_utc")
        # overlap on half-open intervals: start < ex_end AND ex_start < end
        if start_dt < ex_end and ex_start < end_dt:
            raise APIError(ERR_FACILITY_SLOT_CONFLICT, 409, "Facility slot conflict")


def _check_counter_conflict(counter_id: str, start_dt: datetime, end_dt: datetime) -> None:
    """Buffer-extended window [start, end + buffer); a new booking falling inside
    that window is rejected. start == end+buffer is allowed (window open at the
    extended end)."""
    counter = db.urgent_travel_counters[counter_id]
    buffer_min = counter["cleanup_buffer_minutes"]
    for ap in db.appointments.values():
        if ap["resource_kind"] != "URGENT_TRAVEL_COUNTER":
            continue
        if ap["counter_id"] != counter_id or ap["status"] != "BOOKED":
            continue
        ex_start = _parse_instant(ap["start_utc"], "start_utc")
        ex_end = _parse_instant(ap["end_utc"], "end_utc")
        ex_end_buffered = ex_end + timedelta(minutes=buffer_min)
        # Window is [ex_start, ex_end_buffered). New booking conflicts when its
        # interval intersects this half-open window.
        if start_dt < ex_end_buffered and ex_start < end_dt:
            raise APIError(ERR_COUNTER_SLOT_CONFLICT, 409, "Counter slot conflict")


@bp.route("/appointments/<rid>", methods=["GET"])
def get_appointment(rid):
    require_auth(["Applicant", "AcceptanceAgent", "Adjudicator"])
    rec = _appt_or_404(rid)
    return ok_object(serialize(rec), 200)


@bp.route("/appointments", methods=["GET"])
def list_appointments():
    require_auth(["Applicant", "AcceptanceAgent", "Adjudicator"])
    limit, offset = parse_pagination()
    items = list(db.appointments.values())
    application_id = request.args.get("application_id")
    facility_id = request.args.get("facility_id")
    counter_id = request.args.get("counter_id")
    if application_id is not None:
        items = [a for a in items if a["application_id"] == application_id]
    if facility_id is not None:
        items = [a for a in items if a["facility_id"] == facility_id]
    if counter_id is not None:
        items = [a for a in items if a["counter_id"] == counter_id]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.route("/appointments/<rid>/cancel", methods=["POST"])
def cancel_appointment(rid):
    require_auth(["Applicant"])
    appt = _appt_or_404(rid)
    if appt["status"] in ("COMPLETED", "CANCELLED"):
        raise APIError(ERR_ALREADY_TERMINAL, 409, "Appointment is terminal")
    if appt["status"] != "BOOKED":
        raise APIError(ERR_INVALID_STATE, 409, "cancel requires status BOOKED")

    appt["status"] = "CANCELLED"
    touch(appt)

    # Urgent-counter cancellation may flip urgent_travel back to false.
    if appt["resource_kind"] == "URGENT_TRAVEL_COUNTER":
        app_rec = db.applications.get(appt["application_id"])
        if app_rec is not None and not domain.has_booked_urgent(app_rec["id"]):
            if app_rec.get("urgent_travel"):
                app_rec["urgent_travel"] = False
                domain.rederive_fee_if_unpaid(app_rec)

    return ok_object(serialize(appt), 200)


@bp.route("/appointments/<rid>/complete", methods=["POST"])
def complete_appointment(rid):
    require_auth(["AcceptanceAgent"])
    appt = _appt_or_404(rid)
    if appt["status"] in ("COMPLETED", "CANCELLED"):
        raise APIError(ERR_ALREADY_TERMINAL, 409, "Appointment is terminal")
    if appt["status"] != "BOOKED":
        raise APIError(ERR_INVALID_STATE, 409, "complete requires status BOOKED")
    appt["status"] = "COMPLETED"
    touch(appt)
    return ok_object(serialize(appt), 200)
