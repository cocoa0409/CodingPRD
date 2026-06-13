"""Payload factories — one per entity, input fields only.

Each factory returns a dict of source:input fields with sensible defaults and
accepts **overrides for the values a test needs to control. Field names are
PRD-exact.
"""
from .constants import TEST_DEFAULTS

_email_counter = [0]


def unique_email(prefix: str = "patron") -> str:
    """Generate a process-unique email (each test starts on a fresh DB, but a
    single test may create several patrons)."""
    _email_counter[0] += 1
    return f"{prefix}{_email_counter[0]}@test.example.com"


def patron_payload(**overrides) -> dict:
    payload = {
        "email": unique_email(),
        "full_name": "Test Patron",
    }
    payload.update(overrides)
    return payload


def membership_plan_payload(**overrides) -> dict:
    payload = {
        "tier": "HOUSEHOLD",
        "annual_fee_cents": TEST_DEFAULTS["ANNUAL_FEE_CENTS"],
        "household_max": TEST_DEFAULTS["HOUSEHOLD_MAX"],
        "guest_passes_granted": TEST_DEFAULTS["GUEST_PASSES_GRANTED"],
        "member_admission_cents": TEST_DEFAULTS["MEMBER_ADMISSION_CENTS"],
    }
    payload.update(overrides)
    return payload


def membership_payload(plan_id: str, primary_patron_id: str, **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "primary_patron_id": primary_patron_id,
    }
    payload.update(overrides)
    return payload


def household_member_payload(**overrides) -> dict:
    payload = {
        "full_name": "Household Member",
        "relationship": "SPOUSE",
    }
    payload.update(overrides)
    return payload


def slot_payload(**overrides) -> dict:
    payload = {
        "starts_at": "2026-06-10T10:00:00Z",
        "ends_at": "2026-06-10T12:00:00Z",
        "capacity_total": 10,
        "non_member_admission_cents": TEST_DEFAULTS["NON_MEMBER_ADMISSION_CENTS"],
    }
    payload.update(overrides)
    return payload


def special_exhibit_payload(**overrides) -> dict:
    payload = {
        "name": "Test Exhibit",
        "surcharge_cents": TEST_DEFAULTS["SURCHARGE_CENTS"],
    }
    payload.update(overrides)
    return payload


def exhibit_session_payload(**overrides) -> dict:
    payload = {
        "starts_at": "2026-06-10T10:30:00Z",
        "ends_at": "2026-06-10T11:30:00Z",
        "capacity_total": 10,
    }
    payload.update(overrides)
    return payload


def reciprocal_partner_payload(**overrides) -> dict:
    payload = {
        "org_name": "Test Partner",
        "benefit_type": "DISCOUNT",
        "discount_pct": 0.5,
    }
    payload.update(overrides)
    return payload


def order_payload(patron_id: str, slot_id: str, **overrides) -> dict:
    payload = {
        "patron_id": patron_id,
        "slot_id": slot_id,
    }
    payload.update(overrides)
    return payload


def ticket_payload(ticket_type: str, person_name: str = "Person", **overrides) -> dict:
    payload = {
        "ticket_type": ticket_type,
        "person_name": person_name,
    }
    payload.update(overrides)
    return payload
