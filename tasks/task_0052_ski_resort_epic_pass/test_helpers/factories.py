"""Payload factories — one per entity, input fields only.

Each factory returns the input-field payload an endpoint expects, with sensible
defaults that callers override via **overrides. Server-managed and computed
fields (id, status, magnetic_token, scan_count, refund_basis_cents, etc.) are
never included.
"""
import itertools

_tier_cycle = itertools.cycle(["LOCAL", "EPIC_DAY", "FULL_EPIC"])


def create_resort_payload(**overrides) -> dict:
    """POST /resorts — name required; home_network and gate_count optional."""
    defaults = {
        "name": "Test Resort",
        "home_network": "EPIC",
        "gate_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_pass_product_payload(**overrides) -> dict:
    """POST /pass-products — tier and price_cents required; rest optional."""
    defaults = {
        "tier": "FULL_EPIC",
        "price_cents": 8000,
        "blackout_dates": [],
        "buddy_ticket_allotment": 0,
        "buddy_ticket_price_cents": 0,
        "ikon_interchange_enabled": False,
    }
    defaults.update(overrides)
    return defaults


def create_pass_payload(pass_product_id, **overrides) -> dict:
    """POST /passes — pass_product_id and holder_name required."""
    defaults = {
        "pass_product_id": pass_product_id,
        "holder_name": "Test Holder",
    }
    defaults.update(overrides)
    return defaults


def scan_payload(resort_id, presented_token, **overrides) -> dict:
    """POST /passes/{id}/scan — resort_id and presented_token required."""
    defaults = {
        "resort_id": resort_id,
        "presented_token": presented_token,
    }
    defaults.update(overrides)
    return defaults


def create_buddy_ticket_payload(pass_id, resort_id, valid_date, **overrides) -> dict:
    """POST /buddy-tickets — pass_id, resort_id, guest_name, valid_date required."""
    defaults = {
        "pass_id": pass_id,
        "resort_id": resort_id,
        "guest_name": "Test Guest",
        "valid_date": valid_date,
    }
    defaults.update(overrides)
    return defaults


def create_refund_request_payload(pass_id, reason="INJURY", **overrides) -> dict:
    """POST /refund-requests — pass_id and reason required."""
    defaults = {
        "pass_id": pass_id,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def approve_refund_payload(expected_pass_version, **overrides) -> dict:
    """POST /refund-requests/{id}/approve — expected_pass_version required (OCC)."""
    defaults = {
        "expected_pass_version": expected_pass_version,
    }
    defaults.update(overrides)
    return defaults


def create_interchange_agreement_payload(resort_id, max_interchange_days=1,
                                         **overrides) -> dict:
    """POST /interchange-agreements — resort_id and max_interchange_days required."""
    defaults = {
        "resort_id": resort_id,
        "max_interchange_days": max_interchange_days,
    }
    defaults.update(overrides)
    return defaults
