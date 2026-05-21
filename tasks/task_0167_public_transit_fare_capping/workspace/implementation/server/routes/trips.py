"""Trip routes — tap-in, tap-out, list, get."""
from __future__ import annotations

from flask import Blueprint, g, request

from ..auth import require_auth
from ..clock import iso_format, now, parse_iso
from ..common import (
    bump,
    check_occ,
    get_json_body,
    paginate_list,
    parse_pagination,
    require_fields,
    stamp_new,
)
from ..errors import ApiError
from ..fare_logic import (
    apply_cap_minimum,
    compute_provisional_pre_cap,
    fsa_split,
    get_or_create_periods_for,
    increment_period,
    make_transfer_link,
)
from ..response import respond
from ..serializers import trip_view
from ..store import store


bp = Blueprint("trips", __name__, url_prefix="/transit/trips")


@bp.post("")
@require_auth("Rider")
def tap_in():
    body = get_json_body()
    require_fields(body, "card_id", "idempotency_key", "tap_in_at")
    card_id = body["card_id"]
    idem_key = body["idempotency_key"]
    if not isinstance(idem_key, str) or not (1 <= len(idem_key) <= 64):
        raise ApiError("ERR_VALIDATION", "idempotency_key must be a string of length 1..64")
    try:
        tap_in_at = parse_iso(body["tap_in_at"])
    except ValueError as exc:
        raise ApiError("ERR_VALIDATION", str(exc))
    mobile_token_id = body.get("mobile_token_id")

    with store.lock:
        card = store.cards.get(card_id)
        if card is None:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "FareCard not found")
        if card["rider_id"] != g.user_id:
            raise ApiError("ERR_FORBIDDEN", "Riders may only tap in on their own card")

        # Idempotency lookup — first writer wins, duplicate returns 201 + same Trip.
        for existing in store.trips.values():
            if existing["card_id"] == card_id and existing.get("idempotency_key") == idem_key:
                return respond(trip_view(existing), 201)

        # State checks
        if card["status"] != "ACTIVE":
            raise ApiError("ERR_CARD_NOT_ACTIVE", "Card is not ACTIVE")
        for t in store.trips.values():
            if t["card_id"] == card_id and t.get("travel_status") == "TAPPED_IN":
                raise ApiError("ERR_TRIP_ALREADY_OPEN", "Another trip on this card is still TAPPED_IN")

        # Mobile token state
        if mobile_token_id is not None:
            tok = store.mobile_tokens.get(mobile_token_id)
            if tok is None:
                raise ApiError("ERR_REFERENCE_NOT_FOUND", "MobilePaymentToken not found")
            if tok.get("status") != "ACTIVE":
                raise ApiError("ERR_INVALID_STATE", "MobilePaymentToken is not ACTIVE")

        # Validity window
        try:
            card_vf = parse_iso(card["valid_from"])
            card_vu = parse_iso(card["valid_until"])
        except ValueError:
            raise ApiError("ERR_VALIDATION", "Card has invalid validity window")
        if not (card_vf <= tap_in_at <= card_vu):
            raise ApiError("ERR_CARD_OUTSIDE_VALIDITY", "tap_in_at outside card validity window")

        rider = store.riders[card["rider_id"]]

        # Ensure cap periods exist (DAILY + WEEKLY)
        daily, weekly = get_or_create_periods_for(card_id, tap_in_at)

        # Step 1+2: pre-cap fare and eligible prior for transfer link
        pre_cap, prior = compute_provisional_pre_cap(card, rider, tap_in_at)

        # Step 3: cap allocation
        provisional = apply_cap_minimum(pre_cap, daily, weekly)

        # Funds check
        paid_from_fsa, remainder, account = fsa_split(rider, card, provisional)

        # Commit: create the trip + side effects
        trip = {
            "card_id": card_id,
            "idempotency_key": idem_key,
            "tap_in_at": body["tap_in_at"],
            "tap_out_at": None,
            "fare_status": "PROVISIONAL",
            "travel_status": "TAPPED_IN",
            "provisional_fare_cents": provisional,
            "settled_fare_cents": None,
            "transfer_link_id": None,
            "cap_period_id": daily["id"],
            "paid_from_fsa_cents": paid_from_fsa,
        }
        stamp_new(trip)
        store.trips[trip["id"]] = trip

        # Transfer link (if eligible)
        if prior is not None:
            link = make_transfer_link(prior, trip)
            trip["transfer_link_id"] = link["id"]

        # Apply debits
        if account is not None and paid_from_fsa > 0:
            account["balance_cents"] = int(account["balance_cents"]) - paid_from_fsa
            bump(account)
        if remainder > 0:
            card["wallet_balance_cents"] = int(card["wallet_balance_cents"]) - remainder
            bump(card)
        # Increment cap periods
        increment_period(daily, provisional, marker_time=tap_in_at)
        increment_period(weekly, provisional, marker_time=tap_in_at)

    return respond(trip_view(trip), 201)


@bp.get("/<trip_id>")
@require_auth("Rider", "AgencyOfficer", "Auditor")
def get_trip(trip_id: str):
    with store.lock:
        trip = store.trips.get(trip_id)
        if trip is None:
            raise ApiError("ERR_NOT_FOUND", "Trip not found")
        if g.user_role == "Rider":
            card = store.cards.get(trip["card_id"])
            if card is None or card["rider_id"] != g.user_id:
                raise ApiError("ERR_FORBIDDEN", "Riders may only view their own trips")
        return respond(trip_view(trip), 200)


@bp.get("")
@require_auth("Rider", "AgencyOfficer", "Auditor")
def list_trips():
    limit, offset = parse_pagination()
    card_id = request.args.get("card_id")
    rider_id = request.args.get("rider_id")
    fare_status = request.args.get("fare_status")
    travel_status = request.args.get("travel_status")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    dfrom = parse_iso(date_from) if date_from else None
    dto = parse_iso(date_to) if date_to else None

    with store.lock:
        results = []
        for trip in store.trips.values():
            card = store.cards.get(trip["card_id"])
            if card is None:
                continue
            if g.user_role == "Rider" and card["rider_id"] != g.user_id:
                continue
            if card_id and trip["card_id"] != card_id:
                continue
            if rider_id and card["rider_id"] != rider_id:
                continue
            if fare_status and trip.get("fare_status") != fare_status:
                continue
            if travel_status and trip.get("travel_status") != travel_status:
                continue
            if dfrom or dto:
                tap_at = parse_iso(trip["tap_in_at"])
                if dfrom and tap_at < dfrom:
                    continue
                if dto and tap_at > dto:
                    continue
            results.append(trip)
        results.sort(key=lambda t: (t.get("created_at", ""), t["id"]))
        sliced, meta = paginate_list(results, limit, offset)
        payload = [trip_view(t) for t in sliced]
    return respond(payload, 200, list_meta=meta)


@bp.post("/<trip_id>/tap-out")
@require_auth("Rider")
def tap_out(trip_id: str):
    body = get_json_body()
    require_fields(body, "tap_out_at")
    try:
        tap_out_at = parse_iso(body["tap_out_at"])
    except ValueError as exc:
        raise ApiError("ERR_VALIDATION", str(exc))

    with store.lock:
        trip = store.trips.get(trip_id)
        if trip is None:
            raise ApiError("ERR_NOT_FOUND", "Trip not found")
        card = store.cards.get(trip["card_id"])
        if card is None or card["rider_id"] != g.user_id:
            raise ApiError("ERR_FORBIDDEN", "Riders may only tap out their own trip")
        if trip.get("travel_status") != "TAPPED_IN":
            raise ApiError("ERR_INVALID_STATE", "Trip is not TAPPED_IN")
        check_occ(trip, body.get("version"))
        tap_in_at = parse_iso(trip["tap_in_at"])
        if not (tap_out_at > tap_in_at):
            raise ApiError("ERR_TAP_OUT_NOT_AFTER_TAP_IN", "tap_out_at must be strictly after tap_in_at")
        trip["tap_out_at"] = iso_format(tap_out_at)
        trip["travel_status"] = "COMPLETED"
        bump(trip)
    return respond(trip_view(trip), 200)
