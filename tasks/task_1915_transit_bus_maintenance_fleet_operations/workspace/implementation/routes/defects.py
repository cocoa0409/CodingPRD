"""Defect report routes: create, events (triage, road calls, resolve, withdraw)."""
from datetime import timedelta
from datetime import datetime as _dt

from flask import Blueprint, request

from errors import err
from httpkit import (require_roles, body, req_str, req_enum, req_int, req_date,
                     opt_str, opt_date, paginate, sort_default, success)
from store import db, init_common, mark_dirty, fmt_date, clock_date
from services import domain as dom
from services import serializers as ser
from routes.buses import get_bus_or_404, ALL

bp = Blueprint("defects", __name__)


def get_defect_or_404(defect_id):
    d = db["defects"].get(defect_id)
    if d is None:
        raise err("ERR_NOT_FOUND", f"DefectReport {defect_id} not found")
    return d


@bp.post("/fleet/defect-reports")
def create_defect():
    uid, _ = require_roles("Operator")
    data = body()
    bus_id = data.get("bus_id")
    bus = None
    if bus_id is not None:
        bus = db["buses"].get(bus_id)
        if bus is None:
            raise err("ERR_NOT_FOUND", f"Bus {bus_id} not found")
    if bus_id is None:
        raise err("ERR_VALIDATION", "Missing required field: bus_id")
    severity = req_enum(data, "severity", dom.DEFECT_SEVERITIES)
    defect_code = req_enum(data, "defect_code", dom.DEFECT_CODES)
    description = req_str(data, "description")
    odometer_at_report = req_int(data, "odometer_at_report")
    if odometer_at_report < 0:
        raise err("ERR_VALIDATION", "odometer_at_report must be >= 0")
    if bus["service_status"] == "RETIRED":
        raise err("ERR_BUS_RETIRED", "Referenced bus is RETIRED")
    defect = init_common({
        "bus_id": bus["id"],
        "reported_by": uid,
        "severity": severity,
        "defect_code": defect_code,
        "description": description,
        "odometer_at_report": odometer_at_report,
        "status": "OPEN",
        "disposition": None,
        "road_call_mechanic_id": None,
        "defer_until_date": None,
        "defer_justification": None,
        "defer_count": 0,
        "linked_work_order_id": None,
        "resolution": None,
        "flagged_by_log_id": None,
    })
    db["defects"][defect["id"]] = defect
    if severity == "SAFETY_CRITICAL":
        dom.recompute_bus_availability(bus)
        mark_dirty("buses", bus["id"])
        dom.recompute_posture()
    return success(ser.defect(defect), code=201)


@bp.get("/fleet/defect-reports/<defect_id>")
def get_defect(defect_id):
    require_roles(*ALL)
    return success(ser.defect(get_defect_or_404(defect_id)))


@bp.get("/fleet/defect-reports")
def list_defects():
    require_roles(*ALL)
    items = list(db["defects"].values())
    bus_id = request.args.get("bus_id")
    if bus_id is not None:
        items = [d for d in items if d["bus_id"] == bus_id]
    st = request.args.get("status")
    if st is not None:
        items = [d for d in items if d["status"] == st]
    items = sort_default(items)
    page, meta_p = paginate(items)
    return success([ser.defect(d) for d in page], response_type="array",
                   pagination=meta_p)


@bp.get("/fleet/defect-reports/<defect_id>/work-orders")
def defect_wos(defect_id):
    require_roles(*ALL)
    get_defect_or_404(defect_id)
    items = sort_default([w for w in db["work_orders"].values()
                          if w.get("defect_report_id") == defect_id])
    page, meta_p = paginate(items)
    return success([ser.work_order(w) for w in page], response_type="array",
                   pagination=meta_p)


_DEFECT_EVENT_ROLES = {
    "TRIAGE": ("MaintenanceSupervisor",),
    "DISPATCH_ROAD_CALL": ("MaintenanceSupervisor",),
    "ARRIVE_ON_SCENE": ("Mechanic",),
    "CLEAR_ROAD_CALL": ("Mechanic",),
    "RESOLVE": ("MaintenanceSupervisor",),
    "WITHDRAW": ("Operator",),
}

_DEFECT_FROM_STATES = {
    "TRIAGE": {"OPEN"},
    "DISPATCH_ROAD_CALL": {"TRIAGED"},
    "ARRIVE_ON_SCENE": {"ROAD_CALL_DISPATCHED"},
    "CLEAR_ROAD_CALL": {"ON_SCENE"},
    "RESOLVE": {"OPEN", "TRIAGED", "SHOP_QUEUED", "DEFERRED"},
    "WITHDRAW": {"OPEN", "TRIAGED", "DEFERRED"},
}


@bp.post("/fleet/defect-reports/<defect_id>/events")
def defect_event(defect_id):
    uid, role = require_roles("MaintenanceSupervisor", "Mechanic", "Operator")
    d = get_defect_or_404(defect_id)
    data = body()
    event_type = req_enum(data, "event_type", set(_DEFECT_EVENT_ROLES))
    if role not in _DEFECT_EVENT_ROLES[event_type]:
        raise err("ERR_FORBIDDEN", f"Role {role} may not perform {event_type}")
    # ownership gates (priority 2)
    if event_type in ("ARRIVE_ON_SCENE", "CLEAR_ROAD_CALL"):
        if uid != d.get("road_call_mechanic_id"):
            raise err("ERR_FORBIDDEN",
                      "Only the dispatched mechanic may perform this event")
    if event_type == "WITHDRAW":
        if d.get("reported_by") is not None and uid != d["reported_by"]:
            raise err("ERR_FORBIDDEN",
                      "Only the reporting operator may withdraw the defect")
    # state legality
    if d["status"] in dom.DEFECT_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL",
                  f"Defect report is {d['status']}; transitions are forbidden")
    if d["status"] not in _DEFECT_FROM_STATES[event_type]:
        raise err("ERR_INVALID_STATE",
                  f"Cannot {event_type} a defect report in {d['status']}")
    handler = {
        "TRIAGE": _ev_triage,
        "DISPATCH_ROAD_CALL": _ev_dispatch,
        "ARRIVE_ON_SCENE": _ev_arrive,
        "CLEAR_ROAD_CALL": _ev_clear,
        "RESOLVE": _ev_resolve,
        "WITHDRAW": _ev_withdraw,
    }[event_type]
    handler(d, data, uid)
    return success(ser.defect(d))


def _ev_triage(d, data, uid):
    disposition = req_enum(data, "disposition", {"SHOP", "ROAD_CALL", "DEFER"})
    bus = db["buses"][d["bus_id"]]
    if disposition == "SHOP":
        d["status"] = "SHOP_QUEUED"
        d["disposition"] = "SHOP"
    elif disposition == "ROAD_CALL":
        d["status"] = "TRIAGED"
        d["disposition"] = "ROAD_CALL"
    else:  # DEFER
        defer_until = opt_date(data, "defer_until_date")
        justification = opt_str(data, "defer_justification")
        if defer_until is None:
            raise err("ERR_VALIDATION",
                      "defer_until_date is required for disposition DEFER")
        if not justification:
            raise err("ERR_VALIDATION",
                      "defer_justification is required for disposition DEFER")
        today = clock_date()
        # SAFETY_CRITICAL: defer_until_date must equal the clock date
        if d["severity"] == "SAFETY_CRITICAL":
            if defer_until != today:
                raise err("ERR_DEFECT_NOT_DEFERRABLE",
                          "SAFETY_CRITICAL defects may only be deferred to the "
                          "current date")
        else:
            if defer_until < today:
                raise err("ERR_DEFER_DATE_INVALID",
                          "defer_until_date must not be before the clock date")
            window = 7 if d["severity"] == "MAJOR" else 90
            if defer_until > today + timedelta(days=window):
                raise err("ERR_DEFER_DATE_INVALID",
                          f"defer_until_date exceeds the {window}-day window "
                          f"for {d['severity']} defects")
        d["status"] = "DEFERRED"
        d["disposition"] = "DEFER"
        d["defer_until_date"] = fmt_date(defer_until)
        d["defer_justification"] = justification
        d["defer_count"] = d.get("defer_count", 0) + 1
    mark_dirty("defects", d["id"])
    dom.recompute_bus_availability(bus)


def _ev_dispatch(d, data, uid):
    mechanic_id = data.get("mechanic_id")
    if mechanic_id is not None and mechanic_id not in db["mechanics"]:
        raise err("ERR_NOT_FOUND", f"Mechanic {mechanic_id} not found")
    if mechanic_id is None:
        raise err("ERR_VALIDATION", "mechanic_id is required for dispatch")
    required = dom.DEFECT_CERT_MAP.get(d["defect_code"])
    if required:
        dom.require_cert(mechanic_id, required)
    if not dom.mechanic_on_shift(mechanic_id):
        raise err("ERR_MECHANIC_NOT_ON_SHIFT",
                  "Mechanic lacks a CONFIRMED assignment on a PUBLISHED shift "
                  "covering the clock date")
    d["status"] = "ROAD_CALL_DISPATCHED"
    d["road_call_mechanic_id"] = mechanic_id
    mark_dirty("defects", d["id"])
    bus = db["buses"][d["bus_id"]]
    dom.recompute_bus_availability(bus)
    mark_dirty("buses", bus["id"])
    dom.recompute_posture()


def _ev_arrive(d, data, uid):
    d["status"] = "ON_SCENE"
    mark_dirty("defects", d["id"])


def _ev_clear(d, data, uid):
    resolution = req_enum(data, "resolution", {"FIXED_ON_SCENE", "TOWED_IN"})
    bus = db["buses"][d["bus_id"]]
    if resolution == "FIXED_ON_SCENE":
        d["status"] = "RESOLVED"
        d["resolution"] = "ROAD_CALL_FIXED"
    else:
        d["status"] = "SHOP_QUEUED"
        d["resolution"] = "TOWED_IN"
    mark_dirty("defects", d["id"])
    dom.recompute_bus_availability(bus)
    mark_dirty("buses", bus["id"])
    dom.recompute_posture()


def _ev_resolve(d, data, uid):
    if d["severity"] == "SAFETY_CRITICAL":
        raise err("ERR_SAFETY_DEFECT_NEEDS_WORK_ORDER",
                  "SAFETY_CRITICAL defects must be resolved via a closed work "
                  "order")
    for wo in db["work_orders"].values():
        if (wo.get("defect_report_id") == d["id"]
                and wo["status"] not in dom.WO_TERMINAL):
            raise err("ERR_INVALID_STATE",
                      "A non-terminal work order is linked to this defect")
    d["status"] = "RESOLVED"
    d["resolution"] = "MANUAL"
    mark_dirty("defects", d["id"])
    bus = db["buses"][d["bus_id"]]
    dom.recompute_bus_availability(bus)
    mark_dirty("buses", bus["id"])
    dom.recompute_posture()


def _ev_withdraw(d, data, uid):
    d["status"] = "WITHDRAWN"
    mark_dirty("defects", d["id"])
    bus = db["buses"][d["bus_id"]]
    dom.recompute_bus_availability(bus)
    mark_dirty("buses", bus["id"])
    dom.recompute_posture()
