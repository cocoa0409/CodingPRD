"""TripRequest / TripLeg / Invoice-read endpoints and trip state machine."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from httpkit import (
    ApiError, authenticate, ensure_empty_body, err_invalid_request,
    err_invalid_state, err_not_found, err_reference_not_found, get_body,
    paginate, require_member_ownership, require_roles, respond_object,
    sorted_items,
)
from serializers import invoice_json, ledger_json, leg_json, trip_json
from services import (
    blackout_intersects, card_escrow, complete_trip, compute_quoted_hours,
    create_trip_legs, insert_ledger_entry, is_peak_departure,
    leg_swap_multiplier, new_common, touch, trip_legs,
)
from store import db
from util import D, round_hours

bp = Blueprint("trips", __name__)

CATEGORIES = ["LIGHT", "MIDSIZE", "SUPER_MID", "HEAVY"]
TRIP_KINDS = ["ONE_WAY", "ROUND_TRIP"]


def get_trip_or_404(trip_id):
    t = db.trips.get(trip_id)
    if t is None:
        raise err_not_found(f"TripRequest {trip_id} does not exist")
    return t


def _trip_card(trip):
    return db.cards.get(trip["card_id"])


def _deny_trip(trip, reason):
    """QUOTE -> DENIED system transition on a failed confirm precondition."""
    trip["trip_status"] = "DENIED"
    trip["denial_reason"] = reason
    touch(trip)


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------

@bp.post("/cards/<cardId>/trips")
def create_trip(cardId):
    data = get_body([
        {"name": "trip_kind", "type": "enum", "values": TRIP_KINDS, "required": True},
        {"name": "departure_icao", "type": "string", "required": True},
        {"name": "arrival_icao", "type": "string", "required": True},
        {"name": "requested_departure_utc", "type": "datetime", "required": True},
        {"name": "requested_return_utc", "type": "datetime", "required": False},
        {"name": "pax_count", "type": "integer", "required": True},
        {"name": "requested_category", "type": "enum", "values": CATEGORIES,
         "required": True},
    ])
    authenticate()
    require_roles("Member", "Ops")
    card = db.cards.get(cardId)
    if card is None:
        raise err_not_found(f"JetCard {cardId} does not exist")
    require_member_ownership(card["member_id"])
    # Priority 5: card must be ACTIVE.
    if card["card_status"] != "ACTIVE":
        raise ApiError("ERR_CARD_NOT_ACTIVE", 409,
                       "Trip creation requires JetCard.card_status == ACTIVE")
    # ROUND_TRIP schema: return time required; one-way leaves it null.
    if data["trip_kind"] == "ROUND_TRIP" and data["requested_return_utc"] is None:
        raise err_invalid_request(
            "requested_return_utc is required for ROUND_TRIP")
    # Priority 16: return strictly after departure.
    if data["trip_kind"] == "ROUND_TRIP" and not (
            data["requested_return_utc"] > data["requested_departure_utc"]):
        raise ApiError("ERR_INVALID_RETURN_TIME", 422,
                       "requested_return_utc must be strictly after "
                       "requested_departure_utc")

    program = db.programs.get(card["program_id"])
    quoted = compute_quoted_hours(
        program, data["trip_kind"], data["departure_icao"], data["arrival_icao"])
    peak = is_peak_departure(program["id"], data["requested_departure_utc"])

    trip = new_common()
    trip.update({
        "card_id": cardId,
        "trip_kind": data["trip_kind"],
        "departure_icao": data["departure_icao"],
        "arrival_icao": data["arrival_icao"],
        "requested_departure_utc": data["requested_departure_utc"],
        "requested_return_utc": (data["requested_return_utc"]
                                 if data["trip_kind"] == "ROUND_TRIP" else None),
        "pax_count": data["pax_count"],
        "requested_category": data["requested_category"],
        "swap_applied": False,
        "dispatched_aircraft_id": None,
        "trip_status": "QUOTE",
        "denial_reason": None,
        "is_peak_period": peak,
        "quoted_hours": quoted,
        "final_hours": None,
        "sla_met": None,
    })
    db.trips[trip["id"]] = trip
    return respond_object(trip_json(trip), 201)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

@bp.get("/trips/<tripId>")
def get_trip(tripId):
    authenticate()
    require_roles("Ops", "Member")
    trip = get_trip_or_404(tripId)
    card = _trip_card(trip)
    if card is not None:
        require_member_ownership(card["member_id"])
    return respond_object(trip_json(trip))


@bp.get("/cards/<cardId>/trips")
def list_card_trips(cardId):
    authenticate()
    require_roles("Ops", "Member")
    card = db.cards.get(cardId)
    if card is None:
        raise err_not_found(f"JetCard {cardId} does not exist")
    require_member_ownership(card["member_id"])
    items = sorted_items(
        t for t in db.trips.values() if t["card_id"] == cardId)
    flt = request.args.get("trip_status")
    if flt is not None:
        items = [t for t in items if t["trip_status"] == flt]
    return paginate([trip_json(t) for t in items])


@bp.get("/trips/<tripId>/legs")
def list_trip_legs(tripId):
    authenticate()
    require_roles("Ops", "Member")
    trip = get_trip_or_404(tripId)
    card = _trip_card(trip)
    if card is not None:
        require_member_ownership(card["member_id"])
    legs = sorted_items(trip_legs(tripId))
    return paginate([leg_json(lg) for lg in legs])


@bp.get("/trips/<tripId>/invoice")
def get_trip_invoice(tripId):
    authenticate()
    require_roles("Ops", "Member")
    trip = get_trip_or_404(tripId)
    card = _trip_card(trip)
    if card is not None:
        require_member_ownership(card["member_id"])
    invs = [inv for inv in db.invoices.values() if inv["trip_id"] == tripId]
    invs = sorted_items(invs)
    return paginate([invoice_json(i) for i in invs])


# --- Trip-scoped FK reverse-reachability reads ------------------------------

@bp.get("/trips/<id>/hour_bank_ledger")
def list_trip_ledger(id):
    authenticate()
    require_roles("Ops", "Member")
    trip = get_trip_or_404(id)
    card = _trip_card(trip)
    if card is not None:
        require_member_ownership(card["member_id"])
    items = sorted_items(
        e for e in db.ledger.values() if e["trip_id"] == id)
    return paginate([ledger_json(e) for e in items])


@bp.get("/trips/<id>/trip_legs")
def list_trip_legs_fk(id):
    authenticate()
    require_roles("Ops", "Member")
    trip = get_trip_or_404(id)
    card = _trip_card(trip)
    if card is not None:
        require_member_ownership(card["member_id"])
    legs = sorted_items(trip_legs(id))
    return paginate([leg_json(lg) for lg in legs])


@bp.get("/trips/<id>/invoices")
def list_trip_invoices(id):
    authenticate()
    require_roles("Ops", "Member")
    trip = get_trip_or_404(id)
    card = _trip_card(trip)
    if card is not None:
        require_member_ownership(card["member_id"])
    invs = sorted_items(
        inv for inv in db.invoices.values() if inv["trip_id"] == id)
    return paginate([invoice_json(i) for i in invs])


# ---------------------------------------------------------------------------
# Confirm (member-only; failures deny the trip AND surface the error)
# ---------------------------------------------------------------------------

@bp.post("/trips/<tripId>/confirm")
def confirm_trip(tripId):
    ensure_empty_body()
    authenticate()
    require_roles("Member")
    trip = get_trip_or_404(tripId)
    card = _trip_card(trip)
    require_member_ownership(card["member_id"])
    member = db.members.get(card["member_id"])

    if trip["trip_status"] != "QUOTE":
        raise err_invalid_state("Trip is not in QUOTE")

    # Guards in global priority order. A failure moves QUOTE -> DENIED and
    # the corresponding error is surfaced.
    if card["card_status"] != "ACTIVE":
        _deny_trip(trip, "AVAILABILITY_WINDOW")
        raise ApiError("ERR_CARD_NOT_ACTIVE", 409,
                       "Confirm requires JetCard.card_status == ACTIVE")
    if member is None or member["member_status"] != "ACTIVE":
        _deny_trip(trip, "PEAK_RESTRICTED")
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409,
                       "Confirm requires Member.member_status == ACTIVE")
    program = db.programs.get(card["program_id"])
    if program is not None and blackout_intersects(
            program["id"], trip["requested_category"],
            trip["requested_departure_utc"]):
        _deny_trip(trip, "BLACKOUT")
        raise ApiError("ERR_BLACKOUT_PERIOD", 422,
                       "requested_departure_utc intersects a BlackoutWindow "
                       "for the requested category")
    if card["hours_remaining"] < trip["quoted_hours"]:
        _deny_trip(trip, "INSUFFICIENT_HOURS")
        raise ApiError("ERR_INSUFFICIENT_HOURS", 402,
                       "Card.hours_remaining < TripRequest.quoted_hours")

    trip["trip_status"] = "CONFIRMED"
    touch(trip)
    return respond_object(trip_json(trip))


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

@bp.post("/trips/<tripId>/dispatch")
def dispatch_trip(tripId):
    data = get_body([
        {"name": "dispatched_aircraft_id", "type": "string", "required": True},
    ])
    authenticate()
    require_roles("Ops")
    trip = get_trip_or_404(tripId)
    # Priority 4: body FK existence precedes state checks.
    aircraft = db.aircraft.get(data["dispatched_aircraft_id"])
    if aircraft is None:
        raise err_reference_not_found(
            f"Aircraft {data['dispatched_aircraft_id']} does not exist")
    if trip["trip_status"] != "CONFIRMED":
        raise err_invalid_state("Trip is not in CONFIRMED")
    card = _trip_card(trip)
    program = db.programs.get(card["program_id"]) if card else None

    # Priority 10: SLA window guard (lateness fails; early dispatch allowed).
    now = db.now()
    window = timedelta(hours=program["availability_window_hours"])
    sla_met = (now - trip["requested_departure_utc"]) <= window
    if not sla_met:
        raise ApiError("ERR_SLA_WINDOW_MISSED", 422,
                       "Dispatch time exceeds availability_window_hours from "
                       "requested departure")
    # Priority 11: chosen aircraft must be dispatch-eligible (AVAILABLE).
    if aircraft["aircraft_status"] != "AVAILABLE":
        raise ApiError("ERR_NO_AIRCRAFT_AVAILABLE", 422,
                       "Chosen aircraft is not in AVAILABLE status")
    # Priority 12: passenger capacity.
    if trip["pax_count"] > aircraft["seats"]:
        raise ApiError("ERR_PAX_EXCEEDS_CAPACITY", 422,
                       "pax_count exceeds chosen aircraft seats")

    trip["dispatched_aircraft_id"] = aircraft["id"]
    trip["sla_met"] = sla_met
    trip["swap_applied"] = aircraft["category"] != trip["requested_category"]
    aircraft["aircraft_status"] = "IN_SERVICE"
    touch(aircraft)
    create_trip_legs(trip)
    trip["trip_status"] = "DISPATCHED"
    touch(trip)
    return respond_object(trip_json(trip))


# ---------------------------------------------------------------------------
# Depart / complete / cancel / no-show
# ---------------------------------------------------------------------------

@bp.post("/trips/<tripId>/depart")
def depart_trip(tripId):
    ensure_empty_body()
    authenticate()
    require_roles("Ops")
    trip = get_trip_or_404(tripId)
    if trip["trip_status"] != "DISPATCHED":
        raise err_invalid_state("Trip is not in DISPATCHED")
    trip["trip_status"] = "IN_FLIGHT"
    touch(trip)
    return respond_object(trip_json(trip))


@bp.post("/trips/<tripId>/complete")
def complete_trip_endpoint(tripId):
    # Schema: legs = [{leg_seq, actual_block_minutes}, ...]
    raw = request.get_data()
    if raw is None or raw == b"":
        payload = {}
    else:
        try:
            payload = request.get_json(force=True, silent=False)
        except Exception:
            raise err_invalid_request("Request body is not valid JSON")
        if not isinstance(payload, dict):
            raise err_invalid_request("Request body must be a JSON object")
    for key in payload:
        if key != "legs":
            raise err_invalid_request(f"Unrecognized field: {key}")
    legs_in = payload.get("legs")
    if not isinstance(legs_in, list):
        raise err_invalid_request("legs must be a list")
    parsed = []
    for item in legs_in:
        if not isinstance(item, dict):
            raise err_invalid_request("each leg entry must be an object")
        extra = set(item) - {"leg_seq", "id", "actual_block_minutes"}
        if extra:
            raise err_invalid_request(
                f"Unrecognized leg field(s): {sorted(extra)}")
        abm = item.get("actual_block_minutes")
        if not isinstance(abm, int) or isinstance(abm, bool) or abm < 0:
            raise err_invalid_request(
                "actual_block_minutes must be a non-negative integer")
        parsed.append(item)

    authenticate()
    require_roles("Ops")
    trip = get_trip_or_404(tripId)
    if trip["trip_status"] != "IN_FLIGHT":
        raise err_invalid_state("Trip is not in IN_FLIGHT")

    legs = trip_legs(tripId)
    by_seq = {lg["leg_seq"]: lg for lg in legs}
    by_id = {lg["id"]: lg for lg in legs}
    seen = set()
    for item in parsed:
        lg = None
        if item.get("leg_seq") is not None:
            lg = by_seq.get(item["leg_seq"])
        elif item.get("id") is not None:
            lg = by_id.get(item["id"])
        if lg is None:
            raise err_invalid_request("leg entry does not match this trip")
        if lg["id"] in seen:
            raise err_invalid_request("duplicate leg entry")
        seen.add(lg["id"])
        lg["actual_block_minutes"] = item["actual_block_minutes"]
    if len(seen) != len(legs):
        raise err_invalid_request(
            "All TripLeg.actual_block_minutes must be provided")

    card = _trip_card(trip)
    program = db.programs.get(card["program_id"]) if card else None
    complete_trip(program, trip, card)
    return respond_object(trip_json(trip))


@bp.post("/trips/<tripId>/cancel")
def cancel_trip(tripId):
    ensure_empty_body()
    authenticate()
    require_roles("Member", "Ops")
    trip = get_trip_or_404(tripId)
    card = _trip_card(trip)
    if card is not None:
        require_member_ownership(card["member_id"])

    status = trip["trip_status"]
    if status in ("QUOTE", "CONFIRMED"):
        # Member may abandon a quote/confirmed trip; Ops may also cancel.
        trip["trip_status"] = "CANCELED"
        touch(trip)
        return respond_object(trip_json(trip))
    if status == "DISPATCHED":
        # PRD 3.6: cancellation of a dispatched trip is an Ops action.
        from flask import g
        if g.role != "Ops":
            raise ApiError("ERR_UNAUTHORIZED", 403,
                           "Only Ops may cancel a dispatched trip")
        aircraft = db.aircraft.get(trip["dispatched_aircraft_id"])
        if aircraft is not None:
            aircraft["aircraft_status"] = "AVAILABLE"
            touch(aircraft)
        for lg in trip_legs(tripId):
            lg["leg_status"] = "CANCELED"
            touch(lg)
        trip["trip_status"] = "CANCELED"
        touch(trip)
        return respond_object(trip_json(trip))
    raise err_invalid_state(
        f"Trip in {status} cannot be canceled")


@bp.post("/trips/<tripId>/no_show")
def no_show_trip(tripId):
    ensure_empty_body()
    authenticate()
    require_roles("Ops")
    trip = get_trip_or_404(tripId)
    if trip["trip_status"] != "DISPATCHED":
        raise err_invalid_state("Trip is not in DISPATCHED")
    card = _trip_card(trip)
    program = db.programs.get(card["program_id"]) if card else None
    aircraft = db.aircraft.get(trip["dispatched_aircraft_id"])
    dispatched_category = (aircraft["category"] if aircraft
                           else trip["requested_category"])

    # Bill the minimum trip: min billable per leg in hours x swap multiplier.
    mult = leg_swap_multiplier(program, trip, dispatched_category)
    min_hours = round_hours(D(program["min_billable_minutes_per_leg"]) / D(60))
    debit = round_hours(min_hours * mult)
    insert_ledger_entry(card["id"], "TRIP_DEBIT", -debit, trip_id=trip["id"])
    card["hours_remaining"] = round_hours(card["hours_remaining"] - debit)
    touch(card)

    if aircraft is not None:
        aircraft["aircraft_status"] = "AVAILABLE"
        touch(aircraft)
    for lg in trip_legs(tripId):
        lg["leg_status"] = "CANCELED"
        touch(lg)
    trip["trip_status"] = "NO_SHOW"
    touch(trip)
    return respond_object(trip_json(trip))
