from flask import Blueprint

from auth import authenticate, require_role
from db import store
from envelope import success_object, success_list
from errors import raise_err, ERR_DOCK_APPOINTMENT_NOT_FOUND, \
    ERR_SHIPMENT_NOT_FOUND, ERR_INVALID_STATE, ERR_ALREADY_TERMINAL, \
    ERR_DOCK_WINDOW_CONFLICT, ERR_INVALID_REQUEST
from services import stamp_new, touch, ser_dock_appointment, ser_shipment, \
    sorted_rows
from util import new_id, logical_now
from validate import get_body, check_fields, pagination_params, query_filter

bp = Blueprint("dock_appointments", __name__)

READ_ROLES = ["PlantAdmin", "LogisticsCoordinator"]
APPT_STATUSES = {"RESERVED", "OCCUPIED", "COMPLETED", "NO_SHOW", "CANCELLED"}
TERMINAL = ("COMPLETED", "NO_SHOW", "CANCELLED")


def get_appt_or_404(appt_id):
    a = store.dock_appointments.get(appt_id)
    if a is None:
        raise_err(ERR_DOCK_APPOINTMENT_NOT_FOUND,
                  "DockAppointment id does not resolve")
    return a


@bp.post("/dock-appointments")
def create_appointment():
    _, role = authenticate()
    require_role(role, ["LogisticsCoordinator"])
    body = check_fields(get_body(), {
        "shipment_id": ("str", True),
        "dock_door": ("int", True),
        "window_start": ("datetime", True),
        "window_end": ("datetime", True),
    })
    if not (1 <= body["dock_door"] <= 3):
        raise_err(ERR_INVALID_REQUEST, "dock_door must be 1..3")
    if body["window_start"] >= body["window_end"]:
        raise_err(ERR_INVALID_REQUEST,
                  "window_start must be strictly before window_end")
    shipment = store.shipments.get(body["shipment_id"])
    if shipment is None:
        raise_err(ERR_SHIPMENT_NOT_FOUND, "Shipment id does not resolve")
    if shipment["status"] not in ("QUOTED", "BOOKED"):
        raise_err(ERR_INVALID_STATE,
                  "Appointments require a QUOTED or BOOKED shipment")
    # closed-interval conflict: touching endpoints already conflict
    for a in store.dock_appointments.values():
        if a["dock_door"] != body["dock_door"]:
            continue
        if a["status"] not in ("RESERVED", "OCCUPIED"):
            continue
        if (body["window_start"] <= a["window_end"]
                and a["window_start"] <= body["window_end"]):
            raise_err(ERR_DOCK_WINDOW_CONFLICT,
                      "Window conflicts with another appointment on this door")
    appt = {
        "shipment_id": shipment["id"],
        "dock_door": body["dock_door"],
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "status": "RESERVED",
    }
    stamp_new(appt, new_id())
    store.dock_appointments[appt["id"]] = appt
    return success_object(ser_dock_appointment(appt), 201)


@bp.get("/dock-appointments")
def list_appointments():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    shipment_id = query_filter("shipment_id")
    dock_door = query_filter("dock_door")
    status = query_filter("status", APPT_STATUSES)
    limit, offset = pagination_params()
    rows = list(store.dock_appointments.values())
    if shipment_id is not None:
        rows = [a for a in rows if a["shipment_id"] == shipment_id]
    if dock_door is not None:
        try:
            door = int(dock_door)
        except ValueError:
            raise_err(ERR_INVALID_REQUEST, "dock_door must be an integer")
        rows = [a for a in rows if a["dock_door"] == door]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    rows = sorted_rows(rows)
    page = rows[offset:offset + limit]
    return success_list([ser_dock_appointment(a) for a in page], limit,
                        offset, len(rows))


@bp.get("/dock-appointments/<aid>")
def get_appointment(aid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    return success_object(ser_dock_appointment(get_appt_or_404(aid)))


@bp.get("/dock-appointments/<aid>/shipments")
def appointment_shipments(aid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    get_appt_or_404(aid)
    limit, offset = pagination_params()
    rows = [s for s in store.shipments.values()
            if s["booked_appointment_id"] == aid]
    rows = sorted_rows(rows)
    page = rows[offset:offset + limit]
    return success_list([ser_shipment(s) for s in page], limit, offset,
                        len(rows))


@bp.post("/dock-appointments/<aid>/no-show")
def no_show(aid):
    _, role = authenticate()
    require_role(role, ["LogisticsCoordinator"])
    check_fields(get_body(), {})
    appt = get_appt_or_404(aid)
    if appt["status"] in TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "Appointment is in a terminal state")
    if appt["status"] != "RESERVED":
        raise_err(ERR_INVALID_STATE,
                  "Only a RESERVED appointment can be marked no-show")
    now = logical_now()
    if not (now > appt["window_end"]):
        raise_err(ERR_INVALID_STATE,
                  "No-show requires the clock to be past window_end")
    appt["status"] = "NO_SHOW"
    touch(appt)
    # a shipment booked on this appointment is cancelled outright
    for s in store.shipments.values():
        if s["booked_appointment_id"] == appt["id"] and s["status"] == "BOOKED":
            s["status"] = "CANCELLED"
            s["booked_appointment_id"] = None
            touch(s)
    return success_object(ser_dock_appointment(appt))


@bp.post("/dock-appointments/<aid>/cancel")
def cancel_appointment(aid):
    _, role = authenticate()
    require_role(role, ["LogisticsCoordinator"])
    check_fields(get_body(), {})
    appt = get_appt_or_404(aid)
    if appt["status"] in TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "Appointment is in a terminal state")
    if appt["status"] != "RESERVED":
        raise_err(ERR_INVALID_STATE,
                  "Only a RESERVED appointment can be cancelled")
    appt["status"] = "CANCELLED"
    touch(appt)
    # a shipment booked on this appointment reverts to QUOTED
    for s in store.shipments.values():
        if s["booked_appointment_id"] == appt["id"] and s["status"] == "BOOKED":
            s["status"] = "QUOTED"
            s["booked_appointment_id"] = None
            touch(s)
    return success_object(ser_dock_appointment(appt))
