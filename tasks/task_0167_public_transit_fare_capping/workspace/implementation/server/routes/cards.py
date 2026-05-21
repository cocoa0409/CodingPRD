"""FareCard routes."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..clock import now, parse_iso
from ..common import bump, check_occ, get_json_body, positive_int, require_fields, stamp_new
from ..errors import ApiError
from ..response import respond
from ..serializers import card_view
from ..store import store


bp = Blueprint("cards", __name__, url_prefix="/transit/cards")


VALID_DISCOUNT_CLASSES = {"STANDARD", "REDUCED_FARE", "LOW_INCOME"}


def _has_active_reduced_cert(rider_id: str, at_moment) -> bool:
    for cert in store.reduced_fare_certs.values():
        if cert.get("rider_id") != rider_id:
            continue
        if cert.get("status") != "ACTIVE":
            continue
        try:
            vf = parse_iso(cert["valid_from"])
            vu = parse_iso(cert["valid_until"])
        except Exception:
            continue
        if vf <= at_moment <= vu:
            return True
    return False


@bp.post("")
@require_auth("AgencyOfficer", "Rider")
def create_card():
    body = get_json_body()
    require_fields(body, "rider_id", "discount_class", "valid_from", "valid_until")
    rider_id = body["rider_id"]
    discount_class = body["discount_class"]
    if discount_class not in VALID_DISCOUNT_CLASSES:
        raise ApiError("ERR_VALIDATION", "invalid discount_class")
    try:
        valid_from = parse_iso(body["valid_from"])
        valid_until = parse_iso(body["valid_until"])
    except ValueError as exc:
        raise ApiError("ERR_VALIDATION", str(exc))
    if not (valid_until > valid_from):
        raise ApiError("ERR_VALIDATION", "valid_until must be strictly after valid_from")

    with store.lock:
        rider = store.riders.get(rider_id)
        if rider is None:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "Rider not found")
        # RBAC scoping
        if g.user_role == "Rider":
            if g.user_id != rider_id:
                raise ApiError("ERR_FORBIDDEN", "Riders may only issue cards to themselves")
            if discount_class == "REDUCED_FARE":
                raise ApiError("ERR_FORBIDDEN", "Riders cannot self-issue REDUCED_FARE cards")
        # Business referential checks
        if discount_class == "REDUCED_FARE":
            if not _has_active_reduced_cert(rider_id, now()):
                raise ApiError(
                    "ERR_MISSING_REDUCED_FARE_CERTIFICATE",
                    "Rider has no ACTIVE ReducedFareCertificate covering this moment",
                )
        if discount_class == "LOW_INCOME":
            if not rider.get("low_income_verified"):
                raise ApiError(
                    "ERR_MISSING_LOW_INCOME_VERIFICATION",
                    "Rider does not have an active low-income verification",
                )

        card = {
            "rider_id": rider_id,
            "discount_class": discount_class,
            "status": "ACTIVE",
            "valid_from": body["valid_from"],
            "valid_until": body["valid_until"],
            "wallet_balance_cents": 0,
            "mobile_token_id": None,
        }
        stamp_new(card)
        store.cards[card["id"]] = card
    return respond(card_view(card), 201)


def _ensure_card_access(card_id: str, *, must_own: bool = False) -> dict:
    card = store.cards.get(card_id)
    if card is None:
        raise ApiError("ERR_NOT_FOUND", "FareCard not found")
    if g.user_role == "Rider":
        if card["rider_id"] != g.user_id:
            if must_own:
                raise ApiError("ERR_FORBIDDEN", "Riders may only act on their own card")
            raise ApiError("ERR_FORBIDDEN", "Riders may only view their own card")
    return card


@bp.get("/<card_id>")
@require_auth("Rider", "AgencyOfficer", "Auditor")
def get_card(card_id: str):
    with store.lock:
        card = _ensure_card_access(card_id, must_own=False)
        return respond(card_view(card), 200)


@bp.post("/<card_id>/top-up")
@require_auth("Rider", "AgencyOfficer")
def top_up_card(card_id: str):
    body = get_json_body()
    require_fields(body, "amount_cents")
    amount = positive_int(body["amount_cents"], "amount_cents")
    with store.lock:
        card = _ensure_card_access(card_id, must_own=True)
        check_occ(card, body.get("version"))
        if card["status"] == "CLOSED":
            raise ApiError("ERR_INVALID_STATE", "Card is CLOSED")
        card["wallet_balance_cents"] = int(card["wallet_balance_cents"]) + amount
        bump(card)
    return respond(card_view(card), 200)


@bp.post("/<card_id>/suspend")
@require_auth("AgencyOfficer")
def suspend_card(card_id: str):
    body = get_json_body()
    with store.lock:
        card = store.cards.get(card_id)
        if card is None:
            raise ApiError("ERR_NOT_FOUND", "FareCard not found")
        if card["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Card is not ACTIVE")
        check_occ(card, body.get("version"))
        card["status"] = "SUSPENDED"
        bump(card)
    return respond(card_view(card), 200)


@bp.post("/<card_id>/reactivate")
@require_auth("AgencyOfficer")
def reactivate_card(card_id: str):
    body = get_json_body()
    with store.lock:
        card = store.cards.get(card_id)
        if card is None:
            raise ApiError("ERR_NOT_FOUND", "FareCard not found")
        if card["status"] != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE", "Card is not SUSPENDED")
        check_occ(card, body.get("version"))
        card["status"] = "ACTIVE"
        bump(card)
    return respond(card_view(card), 200)


@bp.post("/<card_id>/close")
@require_auth("Rider")
def close_card(card_id: str):
    body = get_json_body()
    with store.lock:
        card = store.cards.get(card_id)
        if card is None:
            raise ApiError("ERR_NOT_FOUND", "FareCard not found")
        if card["rider_id"] != g.user_id:
            raise ApiError("ERR_FORBIDDEN", "Riders may only close their own card")
        if card["status"] == "CLOSED":
            raise ApiError("ERR_INVALID_STATE", "Card is already CLOSED")
        check_occ(card, body.get("version"))
        # Reject if any trip on this card is still TAPPED_IN
        for trip in store.trips.values():
            if trip["card_id"] == card_id and trip.get("travel_status") == "TAPPED_IN":
                raise ApiError("ERR_INVALID_STATE", "Cannot close: trip still TAPPED_IN")
        card["status"] = "CLOSED"
        card["wallet_balance_cents"] = 0
        # Clear bound mobile token's link
        token_id = card.get("mobile_token_id")
        if token_id:
            token = store.mobile_tokens.get(token_id)
            if token is not None and token.get("bound_card_id") == card_id:
                token["bound_card_id"] = None
                bump(token)
        bump(card)
    return respond(card_view(card), 200)
