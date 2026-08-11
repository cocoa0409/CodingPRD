"""Installers and install appointments."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
from middleware import (require_roles, get_body, req_str, req_dt, query_enum,
                        APPT_STATUSES)
from response import ok, list_ok
from services import create_record, touch, ser

bp = Blueprint("installs", __name__)

TERMINAL_APPT = {"COMPLETED", "CANCELLED", "NO_SHOW"}
TRAVEL_BUFFER = timedelta(minutes=30)


# ------------------------------------------------------------- installers --

@bp.post("/v1/installers")
def create_installer():
    require_roles(["PlatformAdmin"])
    b = get_body()
    rec = create_record(db.installers, {
        "full_name": req_str(b, "full_name"),
        "region": req_str(b, "region"),
    })
    return ok(ser(rec), 201)


@bp.get("/v1/installers/<installer_id>")
def get_installer(installer_id):
    role, uid = require_roles(["PlatformAdmin", "Installer"])
    inst = db.installers.get(installer_id)
    if inst is None:
        raise errors.not_found("Installer not found")
    if role == "Installer" and uid != installer_id:
        raise errors.ownership()
    return ok(ser(inst))


@bp.get("/v1/installers")
def list_installers():
    require_roles(["PlatformAdmin"])
    return list_ok(list(db.installers.values()), ser)


# ----------------------------------------------------------- appointments --

def _get_appt(appointment_id):
    a = db.appointments.get(appointment_id)
    if a is None:
        raise errors.not_found("Install appointment not found")
    return a


def _installer_conflict(installer_id, s, e, exclude_id=None):
    for a in db.appointments.values():
        if a["installer_id"] != installer_id or a["status"] in TERMINAL_APPT:
            continue
        if exclude_id is not None and a["id"] == exclude_id:
            continue
        ws = a["window_start"] - TRAVEL_BUFFER
        we = a["window_end"] + TRAVEL_BUFFER
        if s < we and ws < e:
            return True
    return False


def _senior_conflict(senior_id, s, e, exclude_id=None):
    for a in db.appointments.values():
        if a["senior_id"] != senior_id or a["status"] in TERMINAL_APPT:
            continue
        if exclude_id is not None and a["id"] == exclude_id:
            continue
        if s <= a["window_end"] and a["window_start"] <= e:
            return True
    return False


def _validate_window(senior_id, installer_id, s, e, exclude_id=None):
    """Pinned order: duration -> installer overlap -> senior overlap -> past."""
    minutes = (e - s).total_seconds() / 60
    if minutes < 60 or minutes > 240:
        raise errors.window_too_short()
    if _installer_conflict(installer_id, s, e, exclude_id):
        raise errors.installer_conflict()
    if _senior_conflict(senior_id, s, e, exclude_id):
        raise errors.senior_conflict()
    if not s > db.clock:
        raise errors.window_in_past()


@bp.post("/v1/install-appointments")
def create_appointment():
    require_roles(["PlatformAdmin"])
    b = get_body()
    senior_id = req_str(b, "senior_id")
    kit_id = req_str(b, "kit_id")
    installer_id = req_str(b, "installer_id")
    window_start = req_dt(b, "window_start")
    window_end = req_dt(b, "window_end")
    if senior_id not in db.seniors:
        raise errors.not_found("Senior not found")
    kit = db.kits.get(kit_id)
    if kit is None:
        raise errors.not_found("Sensor kit not found")
    if installer_id not in db.installers:
        raise errors.not_found("Installer not found")
    _validate_window(senior_id, installer_id, window_start, window_end)
    if kit["senior_id"] != senior_id:
        raise errors.kit_senior_mismatch()
    rec = create_record(db.appointments, {
        "senior_id": senior_id,
        "kit_id": kit_id,
        "installer_id": installer_id,
        "window_start": window_start,
        "window_end": window_end,
        "status": "SCHEDULED",
    })
    return ok(ser(rec), 201)


@bp.get("/v1/install-appointments/<appointment_id>")
def get_appointment(appointment_id):
    role, uid = require_roles(["PlatformAdmin", "Installer"])
    a = _get_appt(appointment_id)
    if role == "Installer" and a["installer_id"] != uid:
        raise errors.ownership()
    return ok(ser(a))


@bp.get("/v1/install-appointments")
def list_appointments():
    role, uid = require_roles(["PlatformAdmin", "Installer"])
    recs = list(db.appointments.values())
    if role == "Installer":
        iid = request.args.get("installer_id")
        if iid is not None and iid != uid:
            raise errors.ownership()
        recs = [r for r in recs if r["installer_id"] == uid]
    else:
        iid = request.args.get("installer_id")
        if iid is not None:
            recs = [r for r in recs if r["installer_id"] == iid]
    sid = request.args.get("senior_id")
    if sid is not None:
        recs = [r for r in recs if r["senior_id"] == sid]
    kid = request.args.get("kit_id")
    if kid is not None:
        recs = [r for r in recs if r["kit_id"] == kid]
    st = query_enum("status", APPT_STATUSES)
    if st is not None:
        recs = [r for r in recs if r["status"] == st]
    return list_ok(recs, ser)


@bp.post("/v1/install-appointments/<appointment_id>/confirm")
def confirm_appointment(appointment_id):
    role, uid = require_roles(["Installer"])
    a = _get_appt(appointment_id)
    if a["installer_id"] != uid:
        raise errors.ownership()
    if a["status"] in TERMINAL_APPT:
        raise errors.appointment_terminal()
    if a["status"] != "SCHEDULED":
        raise errors.invalid_state("Appointment is not SCHEDULED")
    a["status"] = "CONFIRMED"
    touch(a)
    return ok(ser(a))


@bp.post("/v1/install-appointments/<appointment_id>/complete")
def complete_appointment(appointment_id):
    role, uid = require_roles(["Installer"])
    a = _get_appt(appointment_id)
    if a["installer_id"] != uid:
        raise errors.ownership()
    if a["status"] in TERMINAL_APPT:
        raise errors.appointment_terminal()
    if a["status"] != "CONFIRMED":
        raise errors.invalid_state("Appointment is not CONFIRMED")
    kit = db.kits.get(a["kit_id"])
    if kit is None or kit["status"] != "DELIVERED":
        raise errors.kit_not_delivered("Kit is not DELIVERED")
    if not (a["window_start"] <= db.clock <= a["window_end"]):
        raise errors.outside_window()
    a["status"] = "COMPLETED"
    touch(a)
    kit["status"] = "INSTALLED"
    touch(kit)
    for d in db.devices.values():
        if d["kit_id"] == kit["id"] and d["status"] == "PROVISIONED":
            d["status"] = "INSTALLED"
            touch(d)
    return ok(ser(a))


@bp.post("/v1/install-appointments/<appointment_id>/cancel")
def cancel_appointment(appointment_id):
    require_roles(["PlatformAdmin"])
    a = _get_appt(appointment_id)
    if a["status"] in TERMINAL_APPT:
        raise errors.appointment_terminal()
    a["status"] = "CANCELLED"
    touch(a)
    return ok(ser(a))


@bp.post("/v1/install-appointments/<appointment_id>/reschedule")
def reschedule_appointment(appointment_id):
    require_roles(["PlatformAdmin"])
    a = _get_appt(appointment_id)
    if a["status"] in TERMINAL_APPT:
        raise errors.appointment_terminal()
    b = get_body()
    window_start = req_dt(b, "window_start")
    window_end = req_dt(b, "window_end")
    _validate_window(a["senior_id"], a["installer_id"], window_start, window_end,
                     exclude_id=a["id"])
    a["window_start"] = window_start
    a["window_end"] = window_end
    a["status"] = "SCHEDULED"
    touch(a)
    return ok(ser(a))
