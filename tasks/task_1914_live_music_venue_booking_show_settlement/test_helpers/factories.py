"""Payload factories — one per creatable resource, input fields only (PRD §4)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _next(tag: str) -> str:
    return f"{tag}-{next(_counter)}"


def create_artist_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "legal_name": f"Artist-{n}",
        "agency": f"Agency-{n}",
        "guarantee_floor_cents": TEST_DEFAULTS["ARTIST"]["guarantee_floor_cents"],
        "deposit_pct": TEST_DEFAULTS["ARTIST"]["deposit_pct"],
    }
    defaults.update(overrides)
    return defaults


def create_booking_agent_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "display_name": f"Agent-{n}",
        "agency_name": f"Agency-{n}",
    }
    defaults.update(overrides)
    return defaults


def create_show_payload(artist_id: str, **overrides) -> dict:
    defaults = {
        "artist_id": artist_id,
        "room": "MAIN_ROOM",
        "show_date": "2026-12-01",
        "doors_at_utc": "2026-12-01T19:00:00Z",
        "curfew_at_utc": "2026-12-01T23:00:00Z",
        "total_capacity": 500,
        "on_sale_at_utc": "2026-08-10T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_date_hold_payload(priority: str, booked_by_agent_id: str,
                             **overrides) -> dict:
    defaults = {
        "priority": priority,
        "booked_by_agent_id": booked_by_agent_id,
    }
    defaults.update(overrides)
    return defaults


def create_challenge_payload(challenger_agent_id: str, challenger_priority: str,
                             **overrides) -> dict:
    defaults = {
        "challenger_agent_id": challenger_agent_id,
        "challenger_priority": challenger_priority,
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(**overrides) -> dict:
    defaults = dict(TEST_DEFAULTS["OFFER"])
    defaults.update(overrides)
    return defaults


def create_ticket_tier_payload(**overrides) -> dict:
    defaults = dict(TEST_DEFAULTS["TIER"])
    defaults.update(overrides)
    return defaults


def create_ticket_sale_payload(tier_id: str, quantity: int, **overrides) -> dict:
    defaults = {"tier_id": tier_id, "quantity": quantity}
    defaults.update(overrides)
    return defaults


def create_support_act_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "artist_name": f"Support-{n}",
        "agreed_fee_cents": 8000,
        "buyout_fee_cents": 6000,
    }
    defaults.update(overrides)
    return defaults


def create_expense_receipt_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "category": "SOUND",
        "amount_cents": 5000,
        "receipt_reference": f"R-{n}",
        "is_recoupable": True,
    }
    defaults.update(overrides)
    return defaults


def create_ancillary_revenue_payload(**overrides) -> dict:
    defaults = {
        "kind": "BAR",
        "gross_cents": 10000,
        "cost_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_wire_transfer_payload(purpose: str, amount_cents: int, **overrides) -> dict:
    defaults = {
        "purpose": purpose,
        "amount_cents": amount_cents,
        "recipient_artist_id": None,
        "support_act_id": None,
        "settlement_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_cancel_payload(reason: str = "VENUE", **overrides) -> dict:
    defaults = {"reason": reason}
    defaults.update(overrides)
    return defaults


def create_postpone_payload(**overrides) -> dict:
    defaults = {
        "new_show_date": "2027-02-01",
        "new_doors_at_utc": "2027-02-01T19:00:00Z",
        "new_curfew_at_utc": "2027-02-01T23:00:00Z",
    }
    defaults.update(overrides)
    return defaults
