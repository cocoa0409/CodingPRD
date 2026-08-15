"""Appointment endpoints (PRD 3.4): the inspection scheduling chain."""

from datetime import timedelta

from flask import request

import webbase as base
import services
import store
from errors import ApiError
from timeutil import clock, parse_instant


def _require_own_appointment(appt):
    """Appraiser-role reads are limited to appointments of their own orders."""
    if base.auth.role == "Appraiser":
        order = services.get_order(appt["order_id"])
        if order["assigned_appraiser_id"] != base.auth.user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")


def register(app):
    @app.route("/appraisal/appointments", methods=["POST"])
    def create_appointment():
        base.auth.require_roles("Appraiser", "FirmAdmin")
        body = base.read_body()
        services.require_fields(body, ["order_id", "appraiser_id", "window_start", "window_end"])
        start_raw = services.require_instant(body, "window_start")
        end_raw = services.require_instant(body, "window_end")
        start_dt = parse_instant(start_raw)
        end_dt = parse_instant(end_raw)
        if not (end_dt > start_dt):
            raise ApiError("ERR_VALIDATION", "window_end must be strictly after window_start.")
        order = services.get_order(body["order_id"])
        appraiser = services.get_appraiser(body["appraiser_id"])
        if order["status"] not in ("ASSIGNED", "INSPECTION_SCHEDULED"):
            raise ApiError("ERR_INVALID_STATE")
        if not (start_dt > clock.now):
            raise ApiError("ERR_WINDOW_IN_PAST")
        # Equality with the order's assignee is enforced at confirm, not here.
        row = store.new_row(
            store.appointments,
            order_id=order["id"],
            appraiser_id=appraiser["id"],
            window_start=start_raw,
            window_end=end_raw,
            status="PROPOSED",
            completed_at=None,
            _window_start_dt=start_dt,
            _window_end_dt=end_dt,
        )
        return base.obj(row, 201)

    @app.route("/appraisal/appointments/<appt_id>", methods=["GET"])
    def get_appointment(appt_id):
        base.auth.require_roles("FirmAdmin", "Appraiser")
        row = services.get_appointment(appt_id)
        _require_own_appointment(row)
        return base.obj(row)

    @app.route("/appraisal/appointments", methods=["GET"])
    def list_appointments():
        base.auth.require_roles("FirmAdmin", "Appraiser")
        order_id = request.args.get("order_id")
        appraiser_id = request.args.get("appraiser_id")
        status = request.args.get("status")
        rows = store.appointments.values()
        if base.auth.role == "Appraiser":
            own_orders = {
                o["id"] for o in store.orders.values()
                if o["assigned_appraiser_id"] == base.auth.user_id
            }
            rows = [r for r in rows if r["order_id"] in own_orders]
        if order_id is not None:
            rows = [r for r in rows if r["order_id"] == order_id]
        if appraiser_id is not None:
            rows = [r for r in rows if r["appraiser_id"] == appraiser_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        return base.listing(rows, request.args)

    @app.route("/appraisal/appointments/<appt_id>/confirm", methods=["POST"])
    def confirm_appointment(appt_id):
        base.auth.require_roles("Appraiser", "FirmAdmin")
        appt = services.get_appointment(appt_id)
        if appt["status"] != "PROPOSED":
            raise ApiError("ERR_INVALID_STATE")
        if not (appt["_window_start_dt"] > clock.now):
            raise ApiError("ERR_WINDOW_IN_PAST")
        order = services.get_order(appt["order_id"])
        if order["status"] not in ("ASSIGNED", "INSPECTION_SCHEDULED"):
            raise ApiError("ERR_INVALID_STATE")
        if appt["appraiser_id"] != order["assigned_appraiser_id"]:
            raise ApiError("ERR_NOT_ASSIGNED_APPRAISER")
        # Travel buffer: [start-30m, end+30m) must not intersect another
        # CONFIRMED appointment of the same appraiser.  Half-open: one buffer
        # ending at the exact instant another begins is not an intersection.
        buf_start = appt["_window_start_dt"] - timedelta(minutes=services.BUFFER_MINUTES)
        buf_end = appt["_window_end_dt"] + timedelta(minutes=services.BUFFER_MINUTES)
        for other in store.appointments.values():
            if other["id"] == appt["id"]:
                continue
            if other["appraiser_id"] != appt["appraiser_id"]:
                continue
            if other["status"] != "CONFIRMED":
                continue
            o_start = other["_window_start_dt"] - timedelta(minutes=services.BUFFER_MINUTES)
            o_end = other["_window_end_dt"] + timedelta(minutes=services.BUFFER_MINUTES)
            if buf_start < o_end and o_start < buf_end:
                raise ApiError("ERR_APPOINTMENT_OVERLAP")
        appt["status"] = "CONFIRMED"
        store.touch(appt)
        if order["status"] == "ASSIGNED":
            order["status"] = "INSPECTION_SCHEDULED"
            store.touch(order)
        return base.obj(appt)

    @app.route("/appraisal/appointments/<appt_id>/reschedule", methods=["POST"])
    def reschedule_appointment(appt_id):
        base.auth.require_roles("Appraiser", "FirmAdmin")
        appt = services.get_appointment(appt_id)
        if appt["status"] != "CONFIRMED":
            raise ApiError("ERR_INVALID_STATE")
        body = base.read_body()
        services.require_fields(body, ["window_start", "window_end"])
        start_raw = services.require_instant(body, "window_start")
        end_raw = services.require_instant(body, "window_end")
        start_dt = parse_instant(start_raw)
        end_dt = parse_instant(end_raw)
        if not (end_dt > start_dt):
            raise ApiError("ERR_VALIDATION", "window_end must be strictly after window_start.")
        if not (start_dt > clock.now):
            raise ApiError("ERR_WINDOW_IN_PAST")
        appt["window_start"] = start_raw
        appt["window_end"] = end_raw
        appt["_window_start_dt"] = start_dt
        appt["_window_end_dt"] = end_dt
        appt["status"] = "PROPOSED"
        store.touch(appt)
        return base.obj(appt)

    @app.route("/appraisal/appointments/<appt_id>/complete", methods=["POST"])
    def complete_appointment(appt_id):
        base.auth.require_roles("Appraiser")
        appt = services.get_appointment(appt_id)
        if appt["status"] != "CONFIRMED":
            raise ApiError("ERR_INVALID_STATE")
        if not (clock.now >= appt["_window_end_dt"]):
            raise ApiError("ERR_WINDOW_IN_PAST")
        appt["status"] = "COMPLETED"
        appt["completed_at"] = store.now_string()
        store.touch(appt)
        order = services.get_order(appt["order_id"])
        if order["status"] == "INSPECTION_SCHEDULED":
            order["status"] = "INSPECTED"
            order["inspection_completed_at"] = store.now_string()
            store.touch(order)
        services.file_workfile(order, "INSPECTION_NOTES")
        return base.obj(appt)

    @app.route("/appraisal/appointments/<appt_id>/no-show", methods=["POST"])
    def no_show_appointment(appt_id):
        base.auth.require_roles("Appraiser", "FirmAdmin")
        appt = services.get_appointment(appt_id)
        if appt["status"] != "CONFIRMED":
            raise ApiError("ERR_INVALID_STATE")
        appt["status"] = "NO_SHOW"
        store.touch(appt)
        # no_show_count is derived from NO_SHOW appointments; the order remains
        # INSPECTION_SCHEDULED and a fresh appointment is required.
        return base.obj(appt)

    @app.route("/appraisal/appointments/<appt_id>/cancel", methods=["POST"])
    def cancel_appointment(appt_id):
        base.auth.require_roles("Appraiser", "FirmAdmin")
        appt = services.get_appointment(appt_id)
        if appt["status"] not in ("PROPOSED", "CONFIRMED"):
            raise ApiError("ERR_INVALID_STATE")
        appt["status"] = "CANCELLED"
        store.touch(appt)
        return base.obj(appt)
