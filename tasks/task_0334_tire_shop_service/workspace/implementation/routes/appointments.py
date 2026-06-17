"""Install-appointment routes (PRD §3.6).

Booking and confirm-reschedule run the same guards, in scaffold §1.4 order:
  9  ERR_BAY_NOT_ALIGNMENT_CAPABLE (422)
  10 ERR_BAY_OUT_OF_SERVICE (409)
  11 ERR_INVALID_INTERVAL (422)
  12 ERR_BAY_TIME_CONFLICT (409)
Booking is additionally OCC-guarded by expected_service_bay_version
(ERR_STALE_BAY_VERSION, 412).
"""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_BAY_NOT_ALIGNMENT_CAPABLE,
    ERR_BAY_OUT_OF_SERVICE,
    ERR_BAY_TIME_CONFLICT,
    ERR_INVALID_INTERVAL,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_BAY_VERSION,
)
from middleware import get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.cascades import order_requires_alignment
from services.validation import (
    lookup_fk_or_404,
    lookup_path_or_404,
    require_fields,
    require_int,
    require_string,
)

bp = Blueprint("appointments", __name__)

# Appointment states that occupy a bay slot for overlap purposes.
BLOCKING_STATES = {"SCHEDULED", "CHECKED_IN"}


def _parse_dt(value, field_name):
    if not isinstance(value, str):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field_name} must be an ISO 8601 string")
    try:
        dt = db.parse_iso_dt(value)
    except (ValueError, TypeError):
        raise APIError(ERR_INVALID_REQUEST, 422,
                       f"{field_name} must be a valid ISO 8601 datetime")
    if dt is None:
        raise APIError(ERR_INVALID_REQUEST, 422,
                       f"{field_name} must be a valid ISO 8601 datetime")
    return dt


def _overlaps(start, end, bay, exclude_id=None):
    """True iff [start, end) + bay.turnover_buffer_min collides with any
    SCHEDULED/CHECKED_IN appointment on the same bay.

    Each appointment occupies [its_start, its_end + buffer). Two such buffered
    half-open intervals collide when one starts before the other ends.
    """
    buffer = timedelta(minutes=bay["turnover_buffer_min"])
    new_block_end = end + buffer
    for a in db.appointments.values():
        if a["service_bay_id"] != bay["id"]:
            continue
        if a["status"] not in BLOCKING_STATES:
            continue
        if exclude_id is not None and a["id"] == exclude_id:
            continue
        a_start = db.parse_iso_dt(a["scheduled_start"])
        a_end = db.parse_iso_dt(a["scheduled_end"]) + buffer
        # half-open overlap: start < other_end AND other_start < end
        if start < a_end and a_start < new_block_end:
            return True
    return False


def _run_booking_guards(start, end, bay, requires_alignment, exclude_id=None):
    """Shared guards for create + confirm-reschedule (scaffold §1.4 ord 9-12)."""
    # 9 — alignment capability.
    if requires_alignment and not bay["alignment_capable"]:
        raise APIError(ERR_BAY_NOT_ALIGNMENT_CAPABLE, 422,
                       "Order requires alignment but bay is not alignment_capable")
    # 10 — bay must be OPEN.
    if bay["status"] != "OPEN":
        raise APIError(ERR_BAY_OUT_OF_SERVICE, 409, "Bay is OUT_OF_SERVICE")
    # 11 — interval well-formed.
    if not (end > start):
        raise APIError(ERR_INVALID_INTERVAL, 422,
                       "scheduled_end must be strictly after scheduled_start")
    # 12 — no overlap on the bay.
    if _overlaps(start, end, bay, exclude_id=exclude_id):
        raise APIError(ERR_BAY_TIME_CONFLICT, 409,
                       "Interval overlaps an existing appointment on the bay")


@bp.post("/appointments")
def create_appointment():
    require_auth(["ServiceAdvisor", "Customer"])()
    body = get_json_body()
    require_fields(
        body,
        ["work_order_id", "service_bay_id", "scheduled_start", "scheduled_end",
         "expected_service_bay_version"],
    )
    work_order_id = require_string(body["work_order_id"], "work_order_id")
    service_bay_id = require_string(body["service_bay_id"], "service_bay_id")
    start = _parse_dt(body["scheduled_start"], "scheduled_start")
    end = _parse_dt(body["scheduled_end"], "scheduled_end")
    expected = require_int(body["expected_service_bay_version"],
                           "expected_service_bay_version")

    with db.mutation_lock:
        # FK existence (priority 4).
        order = lookup_fk_or_404(db.work_orders, work_order_id, "WorkOrder")
        bay = lookup_fk_or_404(db.service_bays, service_bay_id, "ServiceBay")

        requires_alignment = order_requires_alignment(order["id"])

        # Booking guards (ord 9-12).
        _run_booking_guards(start, end, bay, requires_alignment)

        # OCC (priority 17): stale bay version.
        if expected != bay["version"]:
            raise APIError(ERR_STALE_BAY_VERSION, 412,
                           "expected_service_bay_version does not match")

        appt = {
            "work_order_id": work_order_id,
            "service_bay_id": service_bay_id,
            "scheduled_start": body["scheduled_start"],
            "scheduled_end": body["scheduled_end"],
            "requires_alignment": requires_alignment,
            "status": "SCHEDULED",
        }
        db.stamp_common(appt)
        db.appointments[appt["id"]] = appt
        db.bump(bay)  # booking bumps the bay's version
        return ok_object(appt, 201)


@bp.get("/appointments/<aid>")
def get_appointment(aid: str):
    require_auth(["ServiceAdvisor", "Customer", "Technician"])()
    appt = lookup_path_or_404(db.appointments, aid, "InstallAppointment")
    return ok_object(appt, 200)


@bp.get("/appointments")
def list_appointments():
    require_auth(["ServiceAdvisor", "Customer", "Technician"])()
    limit, offset = paginate_params(request.args)
    items = list(db.appointments.values())
    if "service_bay_id" in request.args:
        items = [a for a in items
                 if a["service_bay_id"] == request.args["service_bay_id"]]
    if "work_order_id" in request.args:
        items = [a for a in items
                 if a["work_order_id"] == request.args["work_order_id"]]
    if "status" in request.args:
        items = [a for a in items if a["status"] == request.args["status"]]
    items.sort(key=db.created_then_seq)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.post("/appointments/<aid>/request-reschedule")
def request_reschedule(aid: str):
    require_auth(["Customer", "ServiceAdvisor"])()
    appt = lookup_path_or_404(db.appointments, aid, "InstallAppointment")
    with db.mutation_lock:
        if appt["status"] != "SCHEDULED":
            raise APIError(ERR_INVALID_STATE, 409, "Appointment is not SCHEDULED")
        appt["status"] = "RESCHEDULE_PENDING"
        db.bump(appt)
        return ok_object(appt, 200)


@bp.post("/appointments/<aid>/confirm-reschedule")
def confirm_reschedule(aid: str):
    require_auth(["ServiceAdvisor"])()
    appt = lookup_path_or_404(db.appointments, aid, "InstallAppointment")
    body = get_json_body()
    require_fields(body, ["scheduled_start", "scheduled_end"])
    start = _parse_dt(body["scheduled_start"], "scheduled_start")
    end = _parse_dt(body["scheduled_end"], "scheduled_end")

    with db.mutation_lock:
        if appt["status"] != "RESCHEDULE_PENDING":
            raise APIError(ERR_INVALID_STATE, 409,
                           "Appointment is not RESCHEDULE_PENDING")
        bay = db.service_bays[appt["service_bay_id"]]
        # Re-run the same booking guards (exclude self so it doesn't
        # collide with its own released slot).
        _run_booking_guards(start, end, bay, appt["requires_alignment"],
                            exclude_id=appt["id"])
        appt["scheduled_start"] = body["scheduled_start"]
        appt["scheduled_end"] = body["scheduled_end"]
        appt["status"] = "SCHEDULED"
        db.bump(appt)
        return ok_object(appt, 200)


@bp.post("/appointments/<aid>/check-in")
def check_in(aid: str):
    require_auth(["Technician"])()
    appt = lookup_path_or_404(db.appointments, aid, "InstallAppointment")
    with db.mutation_lock:
        if appt["status"] != "SCHEDULED":
            raise APIError(ERR_INVALID_STATE, 409, "Appointment is not SCHEDULED")
        order = db.work_orders[appt["work_order_id"]]
        if order["fulfillment_status"] != "APPROVED":
            raise APIError(ERR_INVALID_STATE, 409,
                           "Parent work order is not APPROVED")
        bay = db.service_bays[appt["service_bay_id"]]
        if bay["status"] != "OPEN":
            raise APIError(ERR_BAY_OUT_OF_SERVICE, 409,
                           "Cannot check into a bay that is OUT_OF_SERVICE")
        appt["status"] = "CHECKED_IN"
        db.bump(appt)
        return ok_object(appt, 200)


@bp.post("/appointments/<aid>/cancel")
def cancel_appointment(aid: str):
    require_auth(["ServiceAdvisor"])()
    appt = lookup_path_or_404(db.appointments, aid, "InstallAppointment")
    with db.mutation_lock:
        if appt["status"] not in ("SCHEDULED", "RESCHEDULE_PENDING"):
            raise APIError(ERR_INVALID_STATE, 409,
                           "Only SCHEDULED or RESCHEDULE_PENDING appointments can be cancelled")
        appt["status"] = "CANCELLED"
        db.bump(appt)
        return ok_object(appt, 200)
