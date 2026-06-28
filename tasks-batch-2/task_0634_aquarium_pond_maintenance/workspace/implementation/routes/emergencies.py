"""EmergencyCall endpoints (PRD §3.9)."""

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import get_auth, require_roles
from response import object_response
from serializers import emergency_view
import common as C

bp = Blueprint("emergencies", __name__)


@bp.post("/aquatics/emergencies")
def create_emergency():
    _, role = get_auth()
    require_roles(role, {"Dispatcher", "AccountManager"})
    data = C.require_body(request.get_json(silent=True))
    system_id = C.req_str(data, "system_id")
    severity = C.req_enum(data, "severity", {"LOW", "HIGH", "CRITICAL"})
    reported_at = C.req_datetime(data, "reported_at")
    trip_fee_cents = C.req_int(data, "trip_fee_cents", minimum=0)

    if system_id not in store.systems:
        raise ApiError("ERR_NOT_FOUND", "System not found.")

    rec = C.make_record({
        "system_id": system_id,
        "severity": severity,
        "reported_at": reported_at,
        "trip_fee_cents": trip_fee_cents,
        "status": "OPEN",
        "dispatched_visit_id": None,
    })
    store.emergencies[rec["id"]] = rec
    return object_response(emergency_view(rec), 201)


@bp.get("/aquatics/emergencies/<eid>")
def get_emergency(eid):
    _, role = get_auth()
    require_roles(role, {"Dispatcher", "AccountManager", "FieldTech"})
    rec = store.emergencies.get(eid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Emergency call not found.")
    return object_response(emergency_view(rec))


@bp.post("/aquatics/emergencies/<eid>/dispatch")
def dispatch_emergency(eid):
    _, role = get_auth()
    require_roles(role, {"Dispatcher"})
    rec = store.emergencies.get(eid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Emergency call not found.")
    data = C.require_body(request.get_json(silent=True))
    technician_id = C.req_str(data, "technician_id")
    scheduled_start = C.req_datetime(data, "scheduled_start")
    scheduled_end = C.req_datetime(data, "scheduled_end")

    # existence of technician (priority 4)
    tech = store.technicians.get(technician_id)
    if tech is None:
        raise ApiError("ERR_NOT_FOUND", "Technician not found.")

    # state (priority 5)
    if rec["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN call may be dispatched.")

    system = store.systems.get(rec["system_id"])
    # dispatch requires system ACTIVE
    if system is None or system["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Target system must be ACTIVE.")
    # assigned tech active
    if not tech["active"]:
        raise ApiError("ERR_INVALID_STATE", "Assigned technician must be active.")
    # reef certification (priority 7)
    if system["system_kind"] == "REEF" and not tech["certified_for_reef"]:
        raise ApiError("ERR_TECH_NOT_CERTIFIED", "Reef work requires a certified technician.")

    s_dt = C.parse_iso(scheduled_start)
    e_dt = C.parse_iso(scheduled_end)

    # double-booking (priority 9) — applies to emergency dispatch per PRD §3.9
    from routes.visits import _tech_double_booked
    if _tech_double_booked(technician_id, s_dt, e_dt):
        raise ApiError("ERR_TECH_DOUBLE_BOOKED", "Technician double-booked.")

    # create EMERGENCY ServiceVisit in SCHEDULED
    visit = C.make_record({
        "system_id": rec["system_id"],
        "technician_id": technician_id,
        "visit_kind": "EMERGENCY",
        "emergency_call_id": rec["id"],
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "labor_minutes": 0,
        "status": "SCHEDULED",
        "total_cents": 0,
        "invoice_id": None,
    })
    store.visits[visit["id"]] = visit

    rec["dispatched_visit_id"] = visit["id"]
    rec["status"] = "DISPATCHED"
    C.touch(rec)
    return object_response(emergency_view(rec))


@bp.post("/aquatics/emergencies/<eid>/cancel")
def cancel_emergency(eid):
    _, role = get_auth()
    require_roles(role, {"Dispatcher"})
    rec = store.emergencies.get(eid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Emergency call not found.")
    if rec["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN call may be cancelled.")
    rec["status"] = "CANCELLED"
    C.touch(rec)
    return object_response(emergency_view(rec))
