"""Payload factories — one per entity, input fields only."""

from .constants import (
    DEFAULT_CHARTER_FEE_CENTS,
    DEFAULT_YOUTH_DUES_CENTS,
    DEFAULT_ADULT_DUES_CENTS,
    DEFAULT_PROGRAM_YEAR,
    LEADER_USER_ID,
)


def create_council_payload(**overrides) -> dict:
    payload = {
        "name": "Test Council",
        "charter_fee_cents": DEFAULT_CHARTER_FEE_CENTS,
        "youth_dues_cents": DEFAULT_YOUTH_DUES_CENTS,
        "adult_dues_cents": DEFAULT_ADULT_DUES_CENTS,
        "program_year": DEFAULT_PROGRAM_YEAR,
    }
    payload.update(overrides)
    return payload


def create_troop_payload(**overrides) -> dict:
    payload = {
        "unit_number": "U-100",
        "program_type": "SCOUTS",
    }
    payload.update(overrides)
    return payload


def create_member_payload(**overrides) -> dict:
    payload = {
        "member_type": "YOUTH",
        "full_name": "Test Member",
        "birthdate": "2013-03-03",
    }
    payload.update(overrides)
    return payload


def create_dues_invoice_payload(**overrides) -> dict:
    payload = {
        "issued_on": "2026-01-01",
    }
    payload.update(overrides)
    return payload


def create_payment_payload(invoice_id, member_id, amount_cents, **overrides) -> dict:
    payload = {
        "invoice_id": invoice_id,
        "member_id": member_id,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


def create_leader_credential_payload(**overrides) -> dict:
    payload = {
        "requested_by_user_id": LEADER_USER_ID,
    }
    payload.update(overrides)
    return payload


def create_advancement_payload(**overrides) -> dict:
    payload = {
        "kind": "RANK",
        "target": "TENDERFOOT",
        "requirements_total": 1,
    }
    payload.update(overrides)
    return payload


def create_event_payload(**overrides) -> dict:
    payload = {
        "title": "Test Event",
        "starts_at": "2026-07-01T09:00:00Z",
        "ends_at": "2026-07-01T17:00:00Z",
        "capacity": 5,
        "requires_health_form": True,
    }
    payload.update(overrides)
    return payload


def create_event_registration_payload(member_id, **overrides) -> dict:
    payload = {
        "member_id": member_id,
    }
    payload.update(overrides)
    return payload


def create_fundraiser_payload(**overrides) -> dict:
    payload = {
        "product": "COOKIES",
        "unit_price_cents": 500,
        "unit_cost_cents": 200,
        "total_inventory_units": 1000,
    }
    payload.update(overrides)
    return payload


def create_fundraiser_order_payload(fundraiser_id, troop_id, seller_member_id,
                                    units, expected_fundraiser_version, **overrides) -> dict:
    payload = {
        "fundraiser_id": fundraiser_id,
        "troop_id": troop_id,
        "seller_member_id": seller_member_id,
        "units": units,
        "expected_fundraiser_version": expected_fundraiser_version,
    }
    payload.update(overrides)
    return payload


def create_booth_reservation_payload(troop_id, location_code, starts_at, ends_at, **overrides) -> dict:
    payload = {
        "troop_id": troop_id,
        "location_code": location_code,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    payload.update(overrides)
    return payload
