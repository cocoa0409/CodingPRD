"""SurgeEvent and SurgeBooking endpoints (PRD §3.7)."""

from flask import Blueprint, request

from db import STORE, _parse_dt
from errors import (ApiError, ERR_HOUSEHOLD_NOT_FOUND, ERR_OUTSTANDING_BALANCE,
                    ERR_SUBSCRIPTION_NOT_ACTIVE, ERR_SURGE_BOOKING_DAY_CONFLICT,
                    ERR_SURGE_EVENT_NOT_FOUND, ERR_SURGE_EVENT_NOT_OPEN,
                    ERR_ZONE_NOT_FOUND, err_invalid_request, err_invalid_state,
                    err_not_found, err_resident_not_owner, err_stale_version)
from middleware import require_roles
from response import success_list, success_object, parse_pagination
from services.core import (base_record, touch, surge_event_out, surge_booking_out,
                           surge_event_status, _cancel_booking, parse_date)
from services.validate import (require_body, check_unknown_fields, req_str, req_int,
                               req_date)

bp = Blueprint("surge", __name__)

ALL_ROLES = ("Anonymous", "Resident", "Driver", "FieldInspector", "RouteSupervisor",
             "BillingClerk", "ProgramAdmin", "OutreachCoordinator")
BOOKING_READ_ROLES = ("Resident", "ProgramAdmin", "RouteSupervisor")


# ---- SurgeEvent ----

@bp.post("/surge-events")
def create_surge_event():
    require_roles("ProgramAdmin")
    data = require_body(request.get_json(silent=True))
    check_unknown_fields(data, {"zone_id", "event_type", "service_date", "capacity_slots",
                                "booking_window_start", "booking_window_end"})
    zone_id = req_str(data, "zone_id")
    event_type = req_str(data, "event_type")
    if event_type not in ("LEAF_SURGE", "HOLIDAY_TREE"):
        raise err_invalid_request("event_type must be LEAF_SURGE | HOLIDAY_TREE")
    service_date = req_date(data, "service_date")
    capacity = req_int(data, "capacity_slots")
    if capacity < 0:
        raise err_invalid_request("capacity_slots must be >= 0")
    ws = req_str(data, "booking_window_start")
    we = req_str(data, "booking_window_end")
    try:
        ws_dt = _parse_dt(ws)
        we_dt = _parse_dt(we)
    except Exception:
        raise err_invalid_request("booking window values must be ISO 8601 datetimes")
    if we_dt <= ws_dt:
        raise err_invalid_request("booking_window_end must be after booking_window_start")

    if zone_id not in STORE.zones:
        raise err_not_found(ERR_ZONE_NOT_FOUND, "Zone not found")

    e = base_record()
    e.update({
        "zone_id": zone_id, "event_type": event_type, "service_date": service_date,
        "booking_window_start": ws, "booking_window_end": we,
        "capacity_slots": capacity, "reserved_slots": 0,
    })
    STORE.surge_events[e["id"]] = e
    return success_object(surge_event_out(e), 201)


@bp.get("/surge-events")
def list_surge_events():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(STORE.surge_events.values())
    zid = request.args.get("zone_id")
    et = request.args.get("event_type")
    st = request.args.get("status")
    if zid is not None:
        items = [e for e in items if e["zone_id"] == zid]
    if et is not None:
        items = [e for e in items if e["event_type"] == et]
    if st is not None:
        items = [e for e in items if surge_event_status(e) == st]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([surge_event_out(e) for e in page], limit, offset, total)


@bp.get("/surge-events/<eid>")
def get_surge_event(eid):
    require_roles(*ALL_ROLES)
    e = STORE.surge_events.get(eid)
    if not e:
        raise err_not_found(ERR_SURGE_EVENT_NOT_FOUND, "Surge event not found")
    return success_object(surge_event_out(e))


# ---- SurgeBooking ----

@bp.post("/surge-bookings")
def create_booking():
    user_id, role = require_roles("Resident")
    data = require_body(request.get_json(silent=True))
    check_unknown_fields(data, {"surge_event_id", "household_id", "quantity_bundles",
                                "expected_surge_event_version"})
    event_id = req_str(data, "surge_event_id")
    household_id = req_str(data, "household_id")
    qty = req_int(data, "quantity_bundles")
    if qty < 1 or qty > 10:
        raise err_invalid_request("quantity_bundles must be between 1 and 10")
    expected_version = req_int(data, "expected_surge_event_version")

    # Resident ownership
    if user_id != household_id:
        raise err_resident_not_owner()

    # Body FK existence
    event = STORE.surge_events.get(event_id)
    if not event:
        raise err_not_found(ERR_SURGE_EVENT_NOT_FOUND, "Surge event not found")
    hh = STORE.households.get(household_id)
    if not hh:
        raise err_not_found(ERR_HOUSEHOLD_NOT_FOUND, "Household not found")

    # OCC
    if expected_version != event["version"]:
        raise err_stale_version("expected_surge_event_version does not match event version")

    # state: event OPEN
    if surge_event_status(event) != "OPEN":
        raise ApiError(ERR_SURGE_EVENT_NOT_OPEN, "Surge event is not OPEN", 409)

    # state: household holds an ACTIVE subscription
    active_subs = [s for s in STORE.subscriptions.values()
                   if s["household_id"] == household_id and s["status"] == "ACTIVE"]
    if not active_subs:
        raise ApiError(ERR_SUBSCRIPTION_NOT_ACTIVE,
                       "Household must hold an ACTIVE subscription", 409)

    # uniqueness: one booking per household per service_date
    svc_date = event["service_date"]
    for b in STORE.surge_bookings.values():
        if b["household_id"] != household_id or b["status"] not in ("CONFIRMED", "WAITLISTED"):
            continue
        other = STORE.surge_events.get(b["surge_event_id"])
        if other and other["service_date"] == svc_date:
            raise ApiError(ERR_SURGE_BOOKING_DAY_CONFLICT,
                           "Household already has a booking for this service_date", 409)

    # fiscal gate last: no outstanding balance on any household subscription
    for s in STORE.subscriptions.values():
        if s["household_id"] == household_id and s["total_due_cents"] > s["paid_cents"]:
            raise ApiError(ERR_OUTSTANDING_BALANCE,
                           "Household carries a subscription with an outstanding balance", 402)

    # slot allocation
    if event["reserved_slots"] < event["capacity_slots"]:
        status = "CONFIRMED"
        event["reserved_slots"] += 1
    else:
        status = "WAITLISTED"

    b = base_record()
    b.update({
        "surge_event_id": event_id, "household_id": household_id,
        "quantity_bundles": qty, "status": status,
    })
    STORE.surge_bookings[b["id"]] = b
    touch(event)
    return success_object(surge_booking_out(b), 201)


@bp.get("/surge-bookings")
def list_bookings():
    require_roles(*BOOKING_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(STORE.surge_bookings.values())
    eid = request.args.get("surge_event_id")
    hid = request.args.get("household_id")
    st = request.args.get("status")
    if eid is not None:
        items = [b for b in items if b["surge_event_id"] == eid]
    if hid is not None:
        items = [b for b in items if b["household_id"] == hid]
    if st is not None:
        items = [b for b in items if b["status"] == st]
    items.sort(key=lambda b: (b["created_at"], b["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([surge_booking_out(b) for b in page], limit, offset, total)


@bp.get("/surge-bookings/<bid>")
def get_booking(bid):
    require_roles(*BOOKING_READ_ROLES)
    b = STORE.surge_bookings.get(bid)
    if not b:
        raise err_not_found()
    return success_object(surge_booking_out(b))


@bp.post("/surge-bookings/<bid>/cancel")
def cancel_booking(bid):
    user_id, role = require_roles("Resident")
    b = STORE.surge_bookings.get(bid)
    if not b:
        raise err_not_found()
    if user_id != b["household_id"]:
        raise err_resident_not_owner()
    if b["status"] not in ("CONFIRMED", "WAITLISTED"):
        raise err_invalid_state("Booking is not CONFIRMED or WAITLISTED")
    event = STORE.surge_events.get(b["surge_event_id"])
    _cancel_booking(b, event)
    return success_object(surge_booking_out(b))
