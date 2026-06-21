"""Payload factories — one per entity, input fields only.

Each factory returns a fresh dict; pass **overrides to control any field.
Email uniqueness (PRD §3.2) is handled by a module-level counter so repeated
factory calls within a single test never collide.
"""
import itertools

from .constants import SEASON_START, SEASON_END

_email_counter = itertools.count(1)


def unique_email(prefix: str = "holder") -> str:
    """Return a process-unique email so account creation never collides."""
    return f"{prefix}{next(_email_counter)}@example.com"


# --- Section ---
def create_section_payload(**overrides) -> dict:
    payload = {
        "name": "Lower Bowl 101",
        "tier": "STANDARD",
        "base_price_cents": 200000,
    }
    payload.update(overrides)
    return payload


# --- Seat ---
def create_seat_payload(section_id, **overrides) -> dict:
    payload = {
        "section_id": section_id,
        "row_label": "A",
        "seat_number": 1,
        "season_start_date": SEASON_START,
        "season_end_date": SEASON_END,
    }
    payload.update(overrides)
    return payload


# --- Account ---
def create_account_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Holder",
        "email": unique_email(),
    }
    payload.update(overrides)
    return payload


# --- SeasonPlan ---
def create_season_plan_payload(**overrides) -> dict:
    payload = {
        "name": "Full Season 2026",
        "plan_type": "FULL",
        "game_count": 41,
        "price_multiplier_bps": 10000,
    }
    payload.update(overrides)
    return payload


# --- Subscription ---
def create_subscription_payload(account_id, season_plan_id, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "season_plan_id": season_plan_id,
    }
    payload.update(overrides)
    return payload


# --- SeatAssignment ---
def create_seat_assignment_payload(subscription_id, seat_id, **overrides) -> dict:
    payload = {
        "subscription_id": subscription_id,
        "seat_id": seat_id,
    }
    payload.update(overrides)
    return payload


# --- PaymentPlan ---
def create_payment_plan_payload(subscription_id, installment_count=4, **overrides) -> dict:
    payload = {
        "subscription_id": subscription_id,
        "installment_count": installment_count,
    }
    payload.update(overrides)
    return payload


# --- TicketTransfer ---
def create_ticket_transfer_payload(seat_assignment_id, transfer_type, **overrides) -> dict:
    payload = {
        "seat_assignment_id": seat_assignment_id,
        "transfer_type": transfer_type,
    }
    payload.update(overrides)
    return payload


# --- ParkingZone ---
def create_parking_zone_payload(**overrides) -> dict:
    payload = {
        "name": "Lot A",
        "capacity": 10,
        "price_cents": 30000,
    }
    payload.update(overrides)
    return payload


# --- ParkingAddOn ---
def create_parking_addon_payload(subscription_id, parking_zone_id, **overrides) -> dict:
    payload = {
        "subscription_id": subscription_id,
        "parking_zone_id": parking_zone_id,
    }
    payload.update(overrides)
    return payload


__all__ = [
    "unique_email",
    "create_section_payload",
    "create_seat_payload",
    "create_account_payload",
    "create_season_plan_payload",
    "create_subscription_payload",
    "create_seat_assignment_payload",
    "create_payment_plan_payload",
    "create_ticket_transfer_payload",
    "create_parking_zone_payload",
    "create_parking_addon_payload",
]
