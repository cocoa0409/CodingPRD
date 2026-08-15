"""HolidayProductionWindow endpoints (PRD §3.9): seasonal supervised production
windows with half-open overlap rules and the ±24h supervisor conflict guard."""
from datetime import timedelta

from flask import Blueprint, g

from db import logical_now, new_common, store, touch
from errors import err
from middleware import get_or_404, require_client_scope, require_roles
from response import Paginator, created, ok
from services.domain import covering_certificate_exists
from validation import (body_json, req_datetime, req_enum, req_str,
                        require_end_after_start)

bp = Blueprint("holiday_windows", __name__)

HOLIDAY_CODES = ("PASSOVER", "ROSH_HASHANAH", "RAMADAN", "EID_AL_FITR")
SUPERVISION_BUFFER_HOURS = 24


@bp.post("/holiday-windows")
def create_holiday_window():
    data = body_json()
    facility_id = req_str(data, "facility_id")
    holiday_code = req_enum(data, "holiday_code", HOLIDAY_CODES)
    window_start = req_datetime(data, "window_start")
    window_end = req_datetime(data, "window_end")
    require_end_after_start(window_start, window_end, "window_start", "window_end")
    require_roles("ClientContact")
    facility = get_or_404(store.facilities, facility_id, "Facility")
    require_client_scope(facility["client_id"])
    # Half-open [start, end) overlap against REQUESTED/CONFIRMED windows at the
    # same facility; touching endpoints do not intersect.
    for w in store.holiday_windows.values():
        if w["facility_id"] != facility_id:
            continue
        if w["status"] not in ("REQUESTED", "CONFIRMED"):
            continue
        if window_start < w["window_end"] and window_end > w["window_start"]:
            err("ERR_WINDOW_OVERLAP",
                "The window intersects an existing REQUESTED/CONFIRMED window "
                "at this facility")
    window = new_common({
        "facility_id": facility_id,
        "holiday_code": holiday_code,
        "window_start": window_start,
        "window_end": window_end,
        "assigned_supervisor_id": None,
        "status": "REQUESTED",
    })
    store.holiday_windows[window["id"]] = window
    return created(window)


@bp.get("/holiday-windows/<window_id>")
def get_holiday_window(window_id):
    return ok(get_or_404(store.holiday_windows, window_id, "HolidayProductionWindow"))


@bp.get("/facilities/<facility_id>/holiday-windows")
def list_facility_holiday_windows(facility_id):
    get_or_404(store.facilities, facility_id, "Facility")
    p = Paginator()
    rows = [w for w in store.holiday_windows.values()
            if w["facility_id"] == facility_id]
    return ok(p(rows), rtype="array", pagination=p)


@bp.post("/holiday-windows/<window_id>/confirm")
def confirm_holiday_window(window_id):
    data = body_json()
    assigned_supervisor_id = req_str(data, "assigned_supervisor_id")
    require_roles("CertificationReviewer")
    window = get_or_404(store.holiday_windows, window_id, "HolidayProductionWindow")
    if window["status"] != "REQUESTED":
        err("ERR_WINDOW_INVALID_STATE", "confirm requires window status REQUESTED")
    facility = store.facilities.get(window["facility_id"])
    if facility is None or facility["status"] != "APPROVED":
        err("ERR_FACILITY_NOT_APPROVED",
            "confirm requires the hosting facility APPROVED")
    if not covering_certificate_exists(window["facility_id"], window["holiday_code"]):
        err("ERR_NO_COVERING_CERTIFICATE",
            "No ACTIVE certificate covers this facility and holiday scheme")
    # Supervisor conflict: reject iff this window, expanded by 24h on both
    # sides, intersects another CONFIRMED window of the same supervisor,
    # similarly expanded — both inequalities strict.
    buffer = timedelta(hours=SUPERVISION_BUFFER_HOURS)
    for w in store.holiday_windows.values():
        if w["id"] == window_id or w["status"] != "CONFIRMED":
            continue
        if w.get("assigned_supervisor_id") != assigned_supervisor_id:
            continue
        if (window["window_start"] < w["window_end"] + buffer
                and window["window_end"] > w["window_start"] - buffer):
            err("ERR_SUPERVISOR_WINDOW_CONFLICT",
                "The supervisor already holds a CONFIRMED window within the "
                "24-hour supervision buffer")
    window["assigned_supervisor_id"] = assigned_supervisor_id
    window["status"] = "CONFIRMED"
    touch(window)
    return ok(window)


@bp.post("/holiday-windows/<window_id>/complete")
def complete_holiday_window(window_id):
    require_roles("FieldSupervisor")
    window = get_or_404(store.holiday_windows, window_id, "HolidayProductionWindow")
    if g.user_id != window.get("assigned_supervisor_id"):
        err("ERR_NOT_ASSIGNED_INSPECTOR",
            "Only the assigned supervisor may complete this window")
    if window["status"] != "CONFIRMED":
        err("ERR_WINDOW_INVALID_STATE", "complete requires window status CONFIRMED")
    if not logical_now() >= window["window_end"]:
        err("ERR_VISIT_WINDOW_NOT_ACTIVE",
            "The window may be completed no earlier than window_end")
    window["status"] = "COMPLETED"
    touch(window)
    return ok(window)


@bp.post("/holiday-windows/<window_id>/cancel")
def cancel_holiday_window(window_id):
    require_roles("ClientContact", "CertificationReviewer")
    window = get_or_404(store.holiday_windows, window_id, "HolidayProductionWindow")
    if g.user_role == "ClientContact":
        facility = store.facilities.get(window["facility_id"])
        require_client_scope(facility["client_id"] if facility else None)
    if window["status"] not in ("REQUESTED", "CONFIRMED"):
        err("ERR_WINDOW_INVALID_STATE",
            "cancel requires window status REQUESTED or CONFIRMED")
    if any(c for c in store.certificates.values()
           if c.get("holiday_window_id") == window_id
           and c["status"] in ("DRAFT", "ACTIVE", "SUSPENDED")):
        err("ERR_WINDOW_REFERENCED_BY_CERTIFICATE",
            "The window is referenced by a live certificate")
    window["status"] = "CANCELLED"
    touch(window)
    return ok(window)
