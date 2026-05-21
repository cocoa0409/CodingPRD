"""Appointment endpoints."""
from decimal import Decimal

from flask import Blueprint

from .. import store
from ..auth import authed
from ..clock import parse_iso8601
from ..envelope import success_object
from ..errors import raise_error
from ..serializers import serialize_appointment
from ..services.calculations import APPOINTMENT_CHANGE_FEE, MIN_APPT_WINDOW_HOURS, dec2
from ..services.route_planner import (
    assign_planned_times,
    stops_for_route_sorted,
)
from ._helpers import get_json_body, require


bp = Blueprint("appointments", __name__)


def _validate_window(start_raw, end_raw):
    try:
        start = parse_iso8601(start_raw)
        end = parse_iso8601(end_raw)
    except Exception:
        raise_error("ERR_APPOINTMENT_WINDOW_INVALID")
    if start >= end:
        raise_error("ERR_APPOINTMENT_WINDOW_INVALID")
    if (end - start).total_seconds() < MIN_APPT_WINDOW_HOURS * 3600:
        raise_error("ERR_APPOINTMENT_WINDOW_INVALID")
    return start_raw, end_raw


@bp.post("/appointments")
@authed(["Customer", "Dispatcher"])
def create_appointment(user_id, user_role):
    body = get_json_body()
    parcel_id = require(body, "parcel_id")
    start_raw = require(body, "requested_window_start")
    end_raw = require(body, "requested_window_end")

    with store.lock:
        parcel = store.parcels.get(parcel_id)
        if not parcel:
            raise_error("ERR_REFERENCE_NOT_FOUND", "parcel_id not found")
        if user_role == "Customer" and parcel["customer_id"] != user_id:
            raise_error("ERR_FORBIDDEN")
        # State eligibility: PRD §3.5 says appointment may be filed against parcels in
        # SORTED, ON_VEHICLE, OUT_FOR_DELIVERY, EXCEPTION. Otherwise ERR_INVALID_STATE.
        if parcel["status"] not in ("SORTED", "ON_VEHICLE", "OUT_FOR_DELIVERY", "EXCEPTION"):
            raise_error("ERR_INVALID_STATE", "parcel not in an appointable state")
        _validate_window(start_raw, end_raw)

        # Supersede any prior PENDING appointment for this parcel
        for prior in store.appointments.values():
            if prior["parcel_id"] == parcel_id and prior["status"] == "PENDING":
                prior["status"] = "SUPERSEDED"
                store.stamp_update(prior)

        appt = {
            "parcel_id": parcel_id,
            "requested_window_start": start_raw,
            "requested_window_end": end_raw,
            "status": "PENDING",
            "fee_charged": Decimal("0.00"),
        }
        store.stamp_create(appt)
        store.appointments[appt["id"]] = appt
        return success_object(serialize_appointment(appt), status=201)


@bp.post("/appointments/<aid>/accept")
@authed(["Dispatcher"])
def accept_appointment(user_id, user_role, aid):
    with store.lock:
        appt = store.appointments.get(aid)
        if not appt:
            raise_error("ERR_NOT_FOUND", "appointment not found")
        if appt["status"] != "PENDING":
            raise_error("ERR_INVALID_STATE", "appointment must be PENDING")
        parcel = store.parcels.get(appt["parcel_id"])
        if not parcel:
            raise_error("ERR_REFERENCE_NOT_FOUND", "parcel missing")
        if parcel["status"] not in ("SORTED", "ON_VEHICLE", "OUT_FOR_DELIVERY", "EXCEPTION"):
            raise_error("ERR_INVALID_STATE", "parcel not in an appointable state")
        # Re-validate window
        _validate_window(appt["requested_window_start"], appt["requested_window_end"])

        # Overwrite parcel time windows
        parcel["time_window_start"] = appt["requested_window_start"]
        parcel["time_window_end"] = appt["requested_window_end"]
        store.stamp_update(parcel)

        # Fee
        appt["status"] = "ACCEPTED"
        appt["fee_charged"] = dec2(APPOINTMENT_CHANGE_FEE)
        store.stamp_update(appt)

        # If parcel is on a PLANNED route, re-run planned_arrival_assignment.
        for stop in store.route_stops.values():
            if stop["parcel_id"] != parcel["id"]:
                continue
            route = store.routes.get(stop["route_id"])
            if route and route["status"] == "PLANNED":
                stops = stops_for_route_sorted(route["id"])
                assign_planned_times(route, stops)
                store.stamp_update(route)
            break
        return success_object(serialize_appointment(appt))


@bp.post("/appointments/<aid>/reject")
@authed(["Dispatcher"])
def reject_appointment(user_id, user_role, aid):
    with store.lock:
        appt = store.appointments.get(aid)
        if not appt:
            raise_error("ERR_NOT_FOUND", "appointment not found")
        if appt["status"] != "PENDING":
            raise_error("ERR_INVALID_STATE", "appointment must be PENDING")
        appt["status"] = "REJECTED"
        store.stamp_update(appt)
        return success_object(serialize_appointment(appt))
