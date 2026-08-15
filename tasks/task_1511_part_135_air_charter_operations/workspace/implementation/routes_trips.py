"""TripRequest lifecycle endpoints and QuoteLeg itinerary management."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from httpkit import (
    ALL_ROLES, authenticate, ensure_empty_body, err, err_invalid_request,
    get_body, paginate, require_positive, require_roles, respond_object,
    sorted_items,
)
from serializers import quote_leg_json, trip_json
from services import (
    CATEGORIES, FEE_PCT_TIER1, FEE_PCT_TIER2, FEE_PCT_TIER3,
    QUOTE_VALIDITY_HOURS, TIER_FULL_REFUND_HOURS, TIER_HALF_REFUND_HOURS,
    compute_occupied_window, create_payment, get_leg_or_404, get_trip_or_404,
    has_active_window, has_open_grounding_finding, new_common,
    recompute_payment_posture, release_assignment, release_trip_crew,
    reset_crew_vetting, run_quote_price, touch, trip_legs,
)
from store import db
from util import D, round_money

bp = Blueprint("trips", __name__)

REASONS = ["CUSTOMER", "WEATHER", "OPS"]


# ---------------------------------------------------------------------------
# TripRequest
# ---------------------------------------------------------------------------

@bp.post("/charter/trip-requests")
def create_trip():
    authenticate()
    require_roles("SalesAgent")
    data = get_body([
        {"name": "customer_name", "type": "string", "required": True},
        {"name": "customer_email", "type": "string", "required": True},
        {"name": "requested_category", "type": "enum", "values": CATEGORIES,
         "required": True},
        {"name": "origin_icao", "type": "string", "required": True},
        {"name": "destination_icao", "type": "string", "required": True},
        {"name": "departure_at", "type": "datetime", "required": True},
        {"name": "passenger_count", "type": "integer", "required": True},
        {"name": "international", "type": "boolean", "required": True},
    ])
    if data["passenger_count"] < 0:
        raise err_invalid_request("passenger_count must be >= 0")
    t = new_common()
    t.update({
        "customer_name": data["customer_name"],
        "customer_email": data["customer_email"],
        "requested_category": data["requested_category"],
        "origin_icao": data["origin_icao"],
        "destination_icao": data["destination_icao"],
        "departure_at": data["departure_at"],
        "passenger_count": data["passenger_count"],
        "international": data["international"],
        "status": "QUOTE_DRAFT",
        "payment_posture": "UNPAID",
        "quoted_total_cents": None,
        "deposit_required_cents": None,
        "quote_valid_until": None,
        "collected_cents": 0,
        "final_total_cents": None,
        "cancellation_reason": None,
        "cancellation_fee_cents": None,
        "refund_cents": None,
    })
    db.trips[t["id"]] = t
    return respond_object(trip_json(t), 201)


@bp.get("/charter/trip-requests")
def list_trips():
    authenticate()
    require_roles(*ALL_ROLES)
    items = sorted_items(db.trips.values())
    flt_status = request.args.get("status")
    if flt_status is not None:
        items = [t for t in items if t["status"] == flt_status]
    return paginate([trip_json(t) for t in items])


@bp.get("/charter/trip-requests/<trip_id>")
def get_trip(trip_id):
    authenticate()
    require_roles(*ALL_ROLES)
    return respond_object(trip_json(get_trip_or_404(trip_id)))


@bp.post("/charter/trip-requests/<trip_id>/quote")
def quote_trip(trip_id):
    authenticate()
    require_roles("SalesAgent")
    ensure_empty_body()
    t = get_trip_or_404(trip_id)
    if t["status"] != "QUOTE_DRAFT":
        raise err("ERR_TRIP_NOT_QUOTE_DRAFT", 409,
                  "Quoting requires the trip to be in QUOTE_DRAFT")
    if len(trip_legs(trip_id)) == 0:
        raise err_invalid_request("Cannot quote a trip with no legs")
    quoted_total, deposit_required = run_quote_price(t)
    t["quoted_total_cents"] = quoted_total
    t["deposit_required_cents"] = deposit_required
    t["quote_valid_until"] = db.now() + timedelta(hours=QUOTE_VALIDITY_HOURS)
    t["status"] = "QUOTED"
    touch(t)
    # The itinerary may have changed while QUOTE_DRAFT; recompute the
    # buffered occupancy of every TENTATIVE assignment hanging on the trip.
    for a in db.aircraft_assignments.values():
        if a["trip_request_id"] == trip_id and a["status"] == "TENTATIVE":
            start, end = compute_occupied_window(t)
            a["occupied_start_at"] = start
            a["occupied_end_at"] = end
            touch(a)
    return respond_object(trip_json(t))


@bp.post("/charter/trip-requests/<trip_id>/requote")
def requote_trip(trip_id):
    authenticate()
    require_roles("SalesAgent")
    data = get_body([
        {"name": "expected_trip_request_version", "type": "integer",
         "required": True},
    ])
    t = get_trip_or_404(trip_id)
    # OCC is evaluated before the state preconditions (PRD section 2.11).
    if data["expected_trip_request_version"] != t["version"]:
        raise err("ERR_STALE_VERSION", 412,
                  "expected_trip_request_version does not match the trip's "
                  "current version")
    if t["status"] != "QUOTED":
        raise err("ERR_TRIP_NOT_QUOTED", 409,
                  "Requoting requires the trip to be in QUOTED")
    t["quoted_total_cents"] = None
    t["deposit_required_cents"] = None
    t["quote_valid_until"] = None
    t["status"] = "QUOTE_DRAFT"
    touch(t)
    reset_crew_vetting(trip_id)
    return respond_object(trip_json(t))


@bp.post("/charter/trip-requests/<trip_id>/book")
def book_trip(trip_id):
    authenticate()
    require_roles("SalesAgent")
    data = get_body([
        {"name": "deposit_cents", "type": "integer", "required": True},
    ])
    t = get_trip_or_404(trip_id)
    if t["status"] != "QUOTED":
        raise err("ERR_TRIP_NOT_QUOTED", 409,
                  "Booking requires the trip to be in QUOTED")
    if data["deposit_cents"] < t["deposit_required_cents"]:
        raise err("ERR_DEPOSIT_INSUFFICIENT", 402,
                  "deposit_cents is below deposit_required_cents")
    create_payment(trip_id, "DEPOSIT", data["deposit_cents"])
    recompute_payment_posture(t)
    t["status"] = "BOOKED"
    touch(t)
    return respond_object(trip_json(t))


@bp.post("/charter/trip-requests/<trip_id>/cancel")
def cancel_trip(trip_id):
    authenticate()
    require_roles("SalesAgent")
    data = get_body([
        {"name": "reason", "type": "enum", "values": REASONS, "required": True},
    ])
    t = get_trip_or_404(trip_id)
    reason = data["reason"]
    cancellable_from = ("QUOTE_DRAFT", "QUOTED", "BOOKED")
    if reason in ("WEATHER", "OPS"):
        cancellable_from = cancellable_from + ("DISPATCHED",)
    if t["status"] not in cancellable_from:
        raise err("ERR_TRIP_NOT_CANCELLABLE", 409,
                  "The trip cannot be cancelled from its current status for "
                  "this reason")
    if reason == "WEATHER":
        covered = any(
            w["station_icao"] in (t["origin_icao"], t["destination_icao"])
            and w["starts_at"] <= t["departure_at"] <= w["ends_at"]
            for w in db.advisories.values())
        if not covered:
            raise err("ERR_NO_ACTIVE_WEATHER_ADVISORY", 409,
                      "A WEATHER cancellation requires a published advisory "
                      "covering the departure at the origin or destination")

    # cancellation_refund: fee tiers on hours before departure, computed
    # against the collected amount (never the quoted total).
    collected = t["collected_cents"]
    if reason in ("WEATHER", "OPS"):
        fee_pct = Decimal("0")
    else:
        seconds = (t["departure_at"] - db.now()).total_seconds()
        hours_before = D(str(seconds)) / D(3600)
        if hours_before >= TIER_FULL_REFUND_HOURS:
            fee_pct = FEE_PCT_TIER1
        elif hours_before >= TIER_HALF_REFUND_HOURS:
            fee_pct = FEE_PCT_TIER2
        else:
            fee_pct = FEE_PCT_TIER3
    fee = round_money(D(collected) * fee_pct)
    refund = collected - fee

    t["cancellation_reason"] = reason
    t["cancellation_fee_cents"] = fee
    t["refund_cents"] = refund
    if refund > 0:
        create_payment(trip_id, "REFUND", refund)
    t["status"] = "CANCELLED"
    recompute_payment_posture(t)
    touch(t)

    # Cascade: release the trip's aircraft assignments; a released CONFIRMED
    # assignment on an IN_TRIP tail resolves the tail's status.
    released_confirmed_aircraft = []
    for a in db.aircraft_assignments.values():
        if a["trip_request_id"] == trip_id and a["status"] in ("TENTATIVE", "CONFIRMED"):
            was_confirmed = a["status"] == "CONFIRMED"
            release_assignment(a)
            if was_confirmed:
                released_confirmed_aircraft.append(a["aircraft_id"])
    for aircraft_id in released_confirmed_aircraft:
        aircraft = db.aircraft.get(aircraft_id)
        if aircraft is not None and aircraft["status"] == "IN_TRIP":
            if has_active_window(aircraft_id):
                aircraft["status"] = "MAINTENANCE_HOLD"
            else:
                aircraft["status"] = "AVAILABLE"
            touch(aircraft)
    release_trip_crew(trip_id)
    return respond_object(trip_json(t))


@bp.post("/charter/trip-requests/<trip_id>/dispatch")
def dispatch_trip(trip_id):
    authenticate()
    require_roles("DispatchManager")
    ensure_empty_body()
    t = get_trip_or_404(trip_id)
    if t["status"] != "BOOKED":
        raise err("ERR_TRIP_NOT_BOOKED", 409,
                  "Dispatch requires the trip to be in BOOKED")

    confirmed = [a for a in db.aircraft_assignments.values()
                 if a["trip_request_id"] == trip_id and a["status"] == "CONFIRMED"]
    if len(confirmed) != 1:
        raise err("ERR_NO_CONFIRMED_ASSIGNMENT", 409,
                  "Dispatch requires exactly one CONFIRMED aircraft assignment")
    aircraft = db.aircraft[confirmed[0]["aircraft_id"]]

    # Compliance tier, in the pinned sub-order of PRD section 3.8.
    crew = [c for c in db.crew_assignments.values()
            if c["trip_request_id"] == trip_id]
    legal_pic = any(c["duty_role"] == "PIC" and c["status"] == "VETTED"
                    and c["duty_legal"] and c["rest_legal"] for c in crew)
    legal_sic = any(c["duty_role"] == "SIC" and c["status"] == "VETTED"
                    and c["duty_legal"] and c["rest_legal"] for c in crew)
    if not legal_pic or (aircraft["category"] == "HEAVY_JET" and not legal_sic):
        raise err("ERR_CREW_NOT_VETTED", 422,
                  "Dispatch requires a VETTED legal PIC (and SIC for HEAVY_JET)")

    manifest = [p for p in db.passengers.values() if p["trip_request_id"] == trip_id]
    if len(manifest) != t["passenger_count"]:
        raise err("ERR_PASSENGER_MANIFEST_INCOMPLETE", 422,
                  "Manifest count must equal passenger_count")
    if any(p["tsa_status"] != "CLEARED" for p in manifest):
        raise err("ERR_TSA_NOT_CLEARED", 422,
                  "Every passenger must be CLEARED before dispatch")

    if t["international"]:
        permits = [p for p in db.permits.values() if p["trip_request_id"] == trip_id]
        if len(permits) == 0 or any(
                p["required"] and p["status"] != "GRANTED" for p in permits):
            raise err("ERR_PERMIT_NOT_GRANTED", 422,
                      "International dispatch requires every required permit "
                      "to be GRANTED")

    block_total = sum(lg["block_minutes"] for lg in trip_legs(trip_id))
    if aircraft["total_airframe_minutes"] + block_total > aircraft["next_check_due_minutes"]:
        raise err("ERR_CHECK_HOURS_EXCEEDED", 422,
                  "Projected airframe minutes exceed next_check_due_minutes")

    if has_open_grounding_finding(aircraft["id"]):
        raise err("ERR_GROUNDING_FINDING_OPEN", 422,
                  "An OPEN grounding compliance finding blocks dispatch")

    if t["collected_cents"] < t["quoted_total_cents"]:
        raise err("ERR_BALANCE_NOT_SETTLED", 402,
                  "collected_cents must cover quoted_total_cents at dispatch")

    t["status"] = "DISPATCHED"
    touch(t)
    aircraft["status"] = "IN_TRIP"
    touch(aircraft)
    return respond_object(trip_json(t))


# ---------------------------------------------------------------------------
# QuoteLeg
# ---------------------------------------------------------------------------

@bp.post("/charter/quote-legs")
def create_quote_leg():
    authenticate()
    require_roles("SalesAgent")
    data = get_body([
        {"name": "trip_request_id", "type": "string", "required": True},
        {"name": "seq_no", "type": "integer", "required": True},
        {"name": "leg_type", "type": "enum", "values": ["REVENUE", "POSITIONING"],
         "required": True},
        {"name": "origin_icao", "type": "string", "required": True},
        {"name": "destination_icao", "type": "string", "required": True},
        {"name": "block_minutes", "type": "integer", "required": True},
        {"name": "fuel_stop", "type": "boolean", "required": False},
    ])
    require_positive(data["block_minutes"], "block_minutes")
    t = get_trip_or_404(data["trip_request_id"])
    if t["status"] != "QUOTE_DRAFT":
        raise err("ERR_TRIP_NOT_QUOTE_DRAFT", 409,
                  "Legs may only be added while the trip is in QUOTE_DRAFT")
    lg = new_common()
    lg.update({
        "trip_request_id": data["trip_request_id"],
        "seq_no": data["seq_no"],
        "leg_type": data["leg_type"],
        "origin_icao": data["origin_icao"],
        "destination_icao": data["destination_icao"],
        "block_minutes": data["block_minutes"],
        "fuel_stop": data["fuel_stop"] if data["fuel_stop"] is not None else False,
    })
    db.quote_legs[lg["id"]] = lg
    reset_crew_vetting(data["trip_request_id"])
    return respond_object(quote_leg_json(lg), 201)


@bp.get("/charter/quote-legs/<leg_id>")
def get_quote_leg(leg_id):
    authenticate()
    require_roles(*ALL_ROLES)
    return respond_object(quote_leg_json(get_leg_or_404(leg_id)))


@bp.get("/charter/trip-requests/<trip_id>/quote-legs")
def list_trip_legs(trip_id):
    authenticate()
    require_roles(*ALL_ROLES)
    get_trip_or_404(trip_id)
    items = sorted_items(lg for lg in db.quote_legs.values()
                         if lg["trip_request_id"] == trip_id)
    return paginate([quote_leg_json(lg) for lg in items])


@bp.delete("/charter/quote-legs/<leg_id>")
def delete_quote_leg(leg_id):
    authenticate()
    require_roles("SalesAgent")
    ensure_empty_body()
    lg = get_leg_or_404(leg_id)
    t = db.trips.get(lg["trip_request_id"])
    if t is not None and t["status"] != "QUOTE_DRAFT":
        raise err("ERR_TRIP_NOT_QUOTE_DRAFT", 409,
                  "Legs may only be removed while the trip is in QUOTE_DRAFT")
    trip_id = lg["trip_request_id"]
    del db.quote_legs[leg_id]
    reset_crew_vetting(trip_id)
    return "", 204
