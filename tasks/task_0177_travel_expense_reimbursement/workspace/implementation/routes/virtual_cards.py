"""Virtual Card endpoints."""
from __future__ import annotations

from flask import Blueprint

from core.auth import current_user_id, require_roles
from core.envelope import get_json_body, success_response
from core.errors import (
    err_card_limit_exceeds_budget,
    err_cross_entity_state,
    err_invalid_state,
    err_not_found,
    err_reference_not_found,
    err_segregation_of_duties,
    err_validation,
)
from core.serializers import serialize_virtual_card
from core.store import store
from core.utils import is_int, lock
from services.timestamps import stamp_create, stamp_update


bp = Blueprint("virtual_cards", __name__)


def _last4_from_id(card_id: str) -> str:
    """Deterministic last-4 derived from the UUID."""
    hex_part = "".join(ch for ch in card_id if ch.isdigit())
    if len(hex_part) >= 4:
        return hex_part[-4:]
    # Fall back: use ord sums to produce 4 digits
    h = abs(hash(card_id)) % 10000
    return f"{h:04d}"


@bp.post("/virtual-cards")
@require_roles("TRAVELER")
def create_card():
    body = get_json_body()
    for f in ("trip_id", "credit_limit_cents"):
        if body.get(f) is None:
            raise err_validation(f"{f} is required.")
    if not is_int(body["credit_limit_cents"]) or body["credit_limit_cents"] < 0:
        raise err_validation("credit_limit_cents must be a non-negative integer.")

    trip = store.trips.get(body["trip_id"])
    if trip is None:
        raise err_reference_not_found(f"trip_id {body['trip_id']} not found.")

    if trip["status"] != "APPROVED":
        raise err_cross_entity_state(f"Trip {trip['id']} is not APPROVED.")

    if trip["traveler_id"] != current_user_id():
        raise err_segregation_of_duties("Only the owning traveler may request a card.")

    if int(body["credit_limit_cents"]) > int(trip.get("estimated_budget_cents") or 0):
        raise err_card_limit_exceeds_budget(
            f"credit_limit_cents {body['credit_limit_cents']} exceeds trip.estimated_budget_cents {trip['estimated_budget_cents']}."
        )

    with lock():
        rec = {
            "trip_id": trip["id"],
            "card_last4": None,
            "credit_limit_cents": int(body["credit_limit_cents"]),
            "status": "REQUESTED",
            "authorized_amount_cents": 0,
            "locked_reason": None,
        }
        stamp_create(rec)
        store.virtual_cards[rec["id"]] = rec

    return success_response(serialize_virtual_card(rec), status=201)


@bp.get("/virtual-cards/<cid>")
@require_roles("TRAVELER", "FINANCE_REVIEWER", "ADMIN")
def get_card(cid):
    card = store.virtual_cards.get(cid)
    if card is None:
        raise err_not_found(f"VirtualCard {cid} not found.")
    return success_response(serialize_virtual_card(card))


@bp.post("/virtual-cards/<cid>/issue")
@require_roles("FINANCE_REVIEWER")
def issue_card(cid):
    card = store.virtual_cards.get(cid)
    if card is None:
        raise err_not_found(f"VirtualCard {cid} not found.")
    if card["status"] != "REQUESTED":
        raise err_invalid_state(f"VirtualCard status is {card['status']}, not REQUESTED.")

    trip = store.trips.get(card["trip_id"])
    if trip is None:
        raise err_reference_not_found(f"Trip {card['trip_id']} not found.")
    if trip["status"] != "APPROVED":
        raise err_cross_entity_state(f"Trip {trip['id']} is not APPROVED.")

    if int(card["credit_limit_cents"]) > int(trip.get("estimated_budget_cents") or 0):
        raise err_card_limit_exceeds_budget(
            f"credit_limit_cents {card['credit_limit_cents']} exceeds trip.estimated_budget_cents {trip['estimated_budget_cents']}."
        )

    with lock():
        card["status"] = "ISSUED"
        card["card_last4"] = _last4_from_id(card["id"])
        stamp_update(card)
    return success_response(serialize_virtual_card(card))


@bp.post("/virtual-cards/<cid>/activate")
@require_roles("TRAVELER")
def activate_card(cid):
    card = store.virtual_cards.get(cid)
    if card is None:
        raise err_not_found(f"VirtualCard {cid} not found.")
    if card["status"] != "ISSUED":
        raise err_invalid_state(f"VirtualCard status is {card['status']}, not ISSUED.")
    trip = store.trips.get(card["trip_id"])
    if trip is None or trip["traveler_id"] != current_user_id():
        raise err_segregation_of_duties("Only the owning traveler may activate this card.")
    with lock():
        card["status"] = "ACTIVE"
        stamp_update(card)
    return success_response(serialize_virtual_card(card))


@bp.post("/virtual-cards/<cid>/lock")
@require_roles("FINANCE_REVIEWER")
def lock_card(cid):
    card = store.virtual_cards.get(cid)
    if card is None:
        raise err_not_found(f"VirtualCard {cid} not found.")
    if card["status"] != "ACTIVE":
        raise err_invalid_state(f"VirtualCard status is {card['status']}, not ACTIVE.")

    body = get_json_body()
    reason = body.get("locked_reason")
    if not reason:
        raise err_validation("locked_reason is required.")

    with lock():
        card["status"] = "LOCKED"
        card["locked_reason"] = reason
        stamp_update(card)
    return success_response(serialize_virtual_card(card))


@bp.post("/virtual-cards/<cid>/unlock")
@require_roles("FINANCE_REVIEWER")
def unlock_card(cid):
    card = store.virtual_cards.get(cid)
    if card is None:
        raise err_not_found(f"VirtualCard {cid} not found.")
    if card["status"] != "LOCKED":
        raise err_invalid_state(f"VirtualCard status is {card['status']}, not LOCKED.")

    trip = store.trips.get(card["trip_id"])
    if trip is None:
        raise err_reference_not_found("Trip not found.")
    if trip["status"] in {"COMPLETED", "CANCELLED"}:
        raise err_cross_entity_state(f"Trip status {trip['status']} disallows unlock.")

    with lock():
        card["status"] = "ACTIVE"
        card["locked_reason"] = None
        stamp_update(card)
    return success_response(serialize_virtual_card(card))


@bp.post("/virtual-cards/<cid>/close")
@require_roles("FINANCE_REVIEWER")
def close_card(cid):
    card = store.virtual_cards.get(cid)
    if card is None:
        raise err_not_found(f"VirtualCard {cid} not found.")
    if card["status"] != "ACTIVE":
        raise err_invalid_state(f"VirtualCard status is {card['status']}, not ACTIVE.")
    with lock():
        card["status"] = "CLOSED"
        stamp_update(card)
    return success_response(serialize_virtual_card(card))
