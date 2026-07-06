"""Departure endpoints and operational state machine (PRD §3.3, §3.8).

Includes the cascade chains for confirm / depart / complete / cancel-weather /
cancel-ops. All cascades are atomic within the request (PRD §2.8).
"""
from flask import Blueprint, request
import errors
import validate
import serialize
from db import db
from clock import clock
from middleware import require_auth, resolve_reader
from records import new_record, touch
from response import object_response, array_response
from util import parse_datetime
from services import pricing
from services import departures as departure_svc

bp = Blueprint("departures", __name__)

READ_ROLES = {"Operator", "Guide", "Guest", "Anonymous"}


# --- helpers -----------------------------------------------------------------
def _stops_for(departure_id):
    return [s for s in db.stops.values() if s["departure_id"] == departure_id]


def _bookings_for(departure_id):
    return [b for b in db.bookings.values() if b["departure_id"] == departure_id]


def _venue_confirmations_for_stop(stop_id):
    return [vc for vc in db.venue_confirmations.values() if vc["stop_id"] == stop_id]


def _recompute_estimated_commissions(departure):
    """Estimated commission per stop over the forward-looking expected headcount
    (Bookings in {RESERVED, PAID}) (PRD §3.7 estimated variant)."""
    headcount = departure_svc.compute_expected_headcount(departure["id"])
    for stop in _stops_for(departure["id"]):
        venue = db.partner_venues[stop["partner_venue_id"]]
        stop["estimated_commission_cents"] = pricing.commission(
            headcount, venue["tasting_cost_per_guest_cents"], venue["commission_pct"])
        touch(stop)


def _recompute_settled_commissions(departure):
    """Settled commission per stop over CHECKED_IN headcount only
    (PRD §3.7 settled variant)."""
    headcount = departure_svc.checked_in_headcount(departure["id"])
    for stop in _stops_for(departure["id"]):
        venue = db.partner_venues[stop["partner_venue_id"]]
        stop["settled_commission_cents"] = pricing.commission(
            headcount, venue["tasting_cost_per_guest_cents"], venue["commission_pct"])
        touch(stop)


def _release_confirmed_venue_confirmations(departure):
    """Every stop's CONFIRMED venue confirmation -> RELEASED (PRD §3.8)."""
    for stop in _stops_for(departure["id"]):
        for vc in _venue_confirmations_for_stop(stop["id"]):
            if vc["status"] == "CONFIRMED":
                vc["status"] = "RELEASED"
                touch(vc)


# --- create / read -----------------------------------------------------------
@bp.post("/departures")
def create():
    require_auth({"Operator"})
    body = validate.get_json_body()
    validate.require_fields(body, ["tour_product_id", "vehicle_id", "depart_at", "return_at"])
    tour_product_id = body["tour_product_id"]
    vehicle_id = body["vehicle_id"]
    if not isinstance(tour_product_id, str) or not isinstance(vehicle_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "FK fields must be strings")

    # FK existence (priority 4)
    if tour_product_id not in db.tour_products:
        raise errors.err(errors.ERR_FK_NOT_FOUND, "tour_product_id references a non-existent product")
    if vehicle_id not in db.vehicles:
        raise errors.err(errors.ERR_FK_NOT_FOUND, "vehicle_id references a non-existent vehicle")

    depart_raw = body["depart_at"]
    return_raw = body["return_at"]
    if not isinstance(depart_raw, str) or not isinstance(return_raw, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "depart_at/return_at must be strings")
    depart_at = parse_datetime(depart_raw)
    return_at = parse_datetime(return_raw)
    if depart_at is None or return_at is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "depart_at/return_at must be ISO 8601 instants")

    is_private_charter = validate.opt_bool(body, "is_private_charter", default=False)

    # range check (priority 7): return_at strictly after depart_at
    if not (depart_at < return_at):
        validate.out_of_range()

    vehicle = db.vehicles[vehicle_id]
    rec = new_record({
        "tour_product_id": tour_product_id,
        "vehicle_id": vehicle_id,
        "depart_at": depart_raw,
        "return_at": return_raw,
        "is_private_charter": is_private_charter,
        "seat_capacity": vehicle["seat_capacity"],
        "status": "SCHEDULED",
        "cancel_reason": None,
    })
    db.departures[rec["id"]] = rec
    return object_response(serialize.departure(rec), status=201)


@bp.get("/departures")
def list_departures():
    resolve_reader(READ_ROLES)
    limit, offset = validate.parse_pagination()
    tour_product_id = request.args.get("tour_product_id")
    vehicle_id = request.args.get("vehicle_id")
    status = request.args.get("status")
    records = list(db.departures.values())
    if tour_product_id is not None:
        records = [r for r in records if r["tour_product_id"] == tour_product_id]
    if vehicle_id is not None:
        records = [r for r in records if r["vehicle_id"] == vehicle_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, total = validate.paginate(records, limit, offset, serialize.departure)
    return array_response(items, limit, offset, total)


@bp.get("/departures/<did>")
def get_departure(did):
    resolve_reader(READ_ROLES)
    rec = db.departures.get(did)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Departure not found")
    return object_response(serialize.departure(rec), status=200)


# --- transitions -------------------------------------------------------------
@bp.post("/departures/<did>/confirm")
def confirm(did):
    require_auth({"Operator"})
    dep = db.departures.get(did)
    if dep is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Departure not found")
    if dep["status"] != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a SCHEDULED departure can be confirmed")

    # precondition order (PRD §3.8): venue-confirmed, then vehicle, then headcount
    stops = _stops_for(did)
    for stop in stops:
        confirmed = any(vc["status"] == "CONFIRMED"
                        for vc in _venue_confirmations_for_stop(stop["id"]))
        if not confirmed:
            raise errors.err(errors.ERR_VENUE_NOT_CONFIRMED,
                             "A stop lacks a CONFIRMED venue confirmation")

    vehicle = db.vehicles[dep["vehicle_id"]]
    if vehicle["status"] != "AVAILABLE":
        raise errors.err(errors.ERR_VEHICLE_UNAVAILABLE, "Assigned vehicle is not AVAILABLE")

    if departure_svc.compute_expected_headcount(did) < 1:
        raise errors.err(errors.ERR_NO_BOOKINGS, "Departure has no expected guests")

    _recompute_estimated_commissions(dep)
    dep["status"] = "CONFIRMED"
    touch(dep)
    return object_response(serialize.departure(dep), status=200)


@bp.post("/departures/<did>/depart")
def depart(did):
    require_auth({"Guide"})
    dep = db.departures.get(did)
    if dep is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Departure not found")
    if dep["status"] != "CONFIRMED":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a CONFIRMED departure can depart")

    depart_at = parse_datetime(dep["depart_at"])
    if clock.now() < depart_at:
        raise errors.err(errors.ERR_TOO_EARLY_TO_DEPART, "Cannot depart before depart_at")

    # No-show cleanup: every RESERVED booking with payment_status != CAPTURED
    # is auto-cancelled, its seats released; refund computed (0% inside 48h).
    hb = pricing.hours_before(depart_at, clock.now())
    for booking in _bookings_for(did):
        if booking["status"] == "RESERVED" and booking["payment_status"] != "CAPTURED":
            booking["refund_cents"] = pricing.refund(
                booking["amount_paid_cents"], hb, weather_override=False)
            booking["status"] = "CANCELLED"
            # seats released implicitly (status now terminal); departure version
            # bumped once below for the transition.
            touch(booking)

    dep["status"] = "DEPARTED"
    touch(dep)
    return object_response(serialize.departure(dep), status=200)


@bp.post("/departures/<did>/complete")
def complete(did):
    require_auth({"Guide"})
    dep = db.departures.get(did)
    if dep is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Departure not found")
    if dep["status"] != "DEPARTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a DEPARTED departure can complete")

    return_at = parse_datetime(dep["return_at"])
    if clock.now() < return_at:
        raise errors.err(errors.ERR_TOO_EARLY_TO_COMPLETE, "Cannot complete before return_at")

    # settled commission over CHECKED_IN headcount
    _recompute_settled_commissions(dep)
    # each stop PLANNED -> VISITED
    for stop in _stops_for(did):
        if stop["status"] == "PLANNED":
            stop["status"] = "VISITED"
            touch(stop)
    # CHECKED_IN bookings -> COMPLETED
    for booking in _bookings_for(did):
        if booking["status"] == "CHECKED_IN":
            booking["status"] = "COMPLETED"
            touch(booking)

    dep["status"] = "COMPLETED"
    touch(dep)
    return object_response(serialize.departure(dep), status=200)


def _non_terminal_booking(booking):
    return booking["status"] not in ("COMPLETED", "CANCELLED")


@bp.post("/departures/<did>/cancel-weather")
def cancel_weather(did):
    require_auth({"Operator"})
    dep = db.departures.get(did)
    if dep is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Departure not found")
    if dep["status"] not in ("SCHEDULED", "CONFIRMED"):
        raise errors.err(errors.ERR_INVALID_STATE,
                         "Only a SCHEDULED or CONFIRMED departure can be cancelled for weather")
    body = validate.get_json_body()
    validate.require_fields(body, ["cancel_reason"])
    cancel_reason = validate.require_str(body, "cancel_reason")

    # weather override: every non-terminal booking -> CANCELLED with 100% refund
    for booking in _bookings_for(did):
        if _non_terminal_booking(booking):
            booking["refund_cents"] = pricing.refund(
                booking["amount_paid_cents"], 0, weather_override=True)
            if booking["payment_status"] == "CAPTURED":
                booking["payment_status"] = "REFUNDED"
            booking["status"] = "CANCELLED"
            touch(booking)

    _release_confirmed_venue_confirmations(dep)

    dep["cancel_reason"] = cancel_reason
    dep["status"] = "CANCELLED_WEATHER"
    touch(dep)
    return object_response(serialize.departure(dep), status=200)


@bp.post("/departures/<did>/cancel-ops")
def cancel_ops(did):
    require_auth({"Operator"})
    dep = db.departures.get(did)
    if dep is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Departure not found")
    if dep["status"] not in ("SCHEDULED", "CONFIRMED"):
        raise errors.err(errors.ERR_INVALID_STATE,
                         "Only a SCHEDULED or CONFIRMED departure can be cancelled for ops")
    body = validate.get_json_body()
    validate.require_fields(body, ["cancel_reason"])
    cancel_reason = validate.require_str(body, "cancel_reason")

    depart_at = parse_datetime(dep["depart_at"])
    hb = pricing.hours_before(depart_at, clock.now())

    # ops path: lead-time tiered refund (NOT weather override)
    for booking in _bookings_for(did):
        if _non_terminal_booking(booking):
            booking["refund_cents"] = pricing.refund(
                booking["amount_paid_cents"], hb, weather_override=False)
            if booking["refund_cents"] > 0 and booking["payment_status"] == "CAPTURED":
                booking["payment_status"] = "REFUNDED"
            booking["status"] = "CANCELLED"
            touch(booking)

    _release_confirmed_venue_confirmations(dep)

    dep["cancel_reason"] = cancel_reason
    dep["status"] = "CANCELLED_OPS"
    touch(dep)
    return object_response(serialize.departure(dep), status=200)
