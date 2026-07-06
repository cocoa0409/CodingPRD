from datetime import timedelta

from flask import Blueprint, request

import errors
from errors import err
from db import db, base_fields, touch
from clock import parse_iso
from middleware import get_auth, require_role
from response import ok_object, ok_array
from validate import body, require_str, paginate
from routes.common import get_appointment, get_window, get_donor
from routes.specimens import _validate_dt
import domain

bp = Blueprint("scheduling", __name__)


# ---------------------------- Collection Appointments ----------------------------

@bp.post("/collection-appointments")
def create_appt():
    _uid, role = get_auth()
    require_role(role, {"LabTech"})
    data = body()
    donor_id = require_str(data, "donor_id")
    room_code = require_str(data, "room_code")
    ws_raw = _validate_dt(data, "window_start")
    we_raw = _validate_dt(data, "window_end")
    ws = parse_iso(ws_raw)
    we = parse_iso(we_raw)
    if not (we > ws):
        raise err(errors.ERR_INVALID_REQUEST, "window_end must be after window_start")
    get_donor(donor_id)
    # ROOM half-open overlap, no buffer, same room, BOOKED
    for a in db.collection_appointments.values():
        if a["room_code"] != room_code or a["status"] != "BOOKED":
            continue
        a_ws = parse_iso(a["window_start"])
        a_we = parse_iso(a["window_end"])
        if ws < a_we and a_ws < we:
            raise err(errors.ERR_ROOM_WINDOW_CONFLICT, "Room window conflict")
    appt = base_fields(db)
    appt.update({
        "donor_id": donor_id,
        "room_code": room_code,
        "window_start": ws_raw,
        "window_end": we_raw,
        "status": "BOOKED",
    })
    db.collection_appointments[appt["id"]] = appt
    return ok_object(appt, 201)


@bp.get("/collection-appointments/<i>")
def get_appt(i):
    _uid, role = get_auth()
    require_role(role, {"LabTech", "ScreeningOfficer"})
    return ok_object(get_appointment(i))


@bp.get("/collection-appointments")
def list_appts():
    _uid, role = get_auth()
    require_role(role, {"LabTech", "ScreeningOfficer"})
    items = list(db.collection_appointments.values())
    donor_f = request.args.get("donor_id")
    room_f = request.args.get("room_code")
    status_f = request.args.get("status")
    if donor_f is not None:
        items = [a for a in items if a["donor_id"] == donor_f]
    if room_f is not None:
        items = [a for a in items if a["room_code"] == room_f]
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)


@bp.post("/collection-appointments/<i>/complete")
def complete_appt(i):
    _uid, role = get_auth()
    require_role(role, {"LabTech"})
    appt = get_appointment(i)
    if appt["status"] != "BOOKED":
        raise err(errors.ERR_INVALID_STATE, "Appointment not BOOKED")
    appt["status"] = "COMPLETED"
    touch(db, appt)
    return ok_object(appt)


@bp.post("/collection-appointments/<i>/cancel")
def cancel_appt(i):
    _uid, role = get_auth()
    require_role(role, {"LabTech"})
    appt = get_appointment(i)
    if appt["status"] != "BOOKED":
        raise err(errors.ERR_INVALID_STATE, "Appointment not BOOKED")
    appt["status"] = "CANCELLED"
    touch(db, appt)
    return ok_object(appt)


# ---------------------------- Dewar Maintenance Windows ----------------------------

@bp.post("/dewar-maintenance-windows")
def create_window():
    _uid, role = get_auth()
    require_role(role, {"LabTech"})
    data = body()
    dewar_code = require_str(data, "dewar_code")
    ss_raw = _validate_dt(data, "service_start")
    se_raw = _validate_dt(data, "service_end")
    ss = parse_iso(ss_raw)
    se = parse_iso(se_raw)
    if not (se > ss):
        raise err(errors.ERR_INVALID_REQUEST, "service_end must be after service_start")
    buffer = timedelta(hours=domain.SETTLE_BUFFER_HOURS)
    # DEWAR closed-interval overlap with symmetric buffer, same dewar, SCHEDULED
    for w in db.dewar_maintenance_windows.values():
        if w["dewar_code"] != dewar_code or w["status"] != "SCHEDULED":
            continue
        w_ss = parse_iso(w["service_start"])
        w_se = parse_iso(w["service_end"])
        if (ss - buffer) <= w_se and w_ss <= (se + buffer):
            raise err(errors.ERR_DEWAR_WINDOW_CONFLICT, "Dewar window conflict")
    win = base_fields(db)
    win.update({
        "dewar_code": dewar_code,
        "service_start": ss_raw,
        "service_end": se_raw,
        "status": "SCHEDULED",
    })
    db.dewar_maintenance_windows[win["id"]] = win
    return ok_object(win, 201)


@bp.get("/dewar-maintenance-windows/<i>")
def get_win(i):
    _uid, role = get_auth()
    require_role(role, {"LabTech", "ComplianceOfficer"})
    return ok_object(get_window(i))


@bp.get("/dewar-maintenance-windows")
def list_wins():
    _uid, role = get_auth()
    require_role(role, {"LabTech", "ComplianceOfficer"})
    items = list(db.dewar_maintenance_windows.values())
    dewar_f = request.args.get("dewar_code")
    status_f = request.args.get("status")
    if dewar_f is not None:
        items = [w for w in items if w["dewar_code"] == dewar_f]
    if status_f is not None:
        items = [w for w in items if w["status"] == status_f]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)


@bp.post("/dewar-maintenance-windows/<i>/complete")
def complete_win(i):
    _uid, role = get_auth()
    require_role(role, {"LabTech"})
    win = get_window(i)
    if win["status"] != "SCHEDULED":
        raise err(errors.ERR_INVALID_STATE, "Window not SCHEDULED")
    win["status"] = "DONE"
    touch(db, win)
    return ok_object(win)


@bp.post("/dewar-maintenance-windows/<i>/cancel")
def cancel_win(i):
    _uid, role = get_auth()
    require_role(role, {"LabTech"})
    win = get_window(i)
    if win["status"] != "SCHEDULED":
        raise err(errors.ERR_INVALID_STATE, "Window not SCHEDULED")
    win["status"] = "CANCELLED"
    touch(db, win)
    return ok_object(win)
