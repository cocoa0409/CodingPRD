"""Payload factories — one per entity, input fields only.

Each factory provides PRD-valid defaults and accepts **overrides so tests can
control the values they assert on. Field names are PRD-exact.
"""
import itertools

from .constants import (
    EVENT_DATE,
    CEREMONY_START,
    CEREMONY_END,
    RECEPTION_START,
    RECEPTION_END,
)

# Monotonic counter so generated emails are unique across a run within a process.
_email_counter = itertools.count(1)


def unique_email(prefix: str = "client") -> str:
    return f"{prefix}-{next(_email_counter)}@example.com"


# ──────────── Venue ────────────
def create_venue_payload(**overrides) -> dict:
    defaults = {
        "name": "Lakeside Manor",
        "cancellation_tier": "STANDARD",
        "force_majeure_fee_pct": 0.0,
    }
    defaults.update(overrides)
    return defaults


# ──────────── Space ────────────
def create_space_payload(**overrides) -> dict:
    defaults = {
        "name": "Grand Hall",
        "space_kind": "DUAL",
        "max_capacity": 200,
        "base_rental_cents": 500_000,
        "turnover_buffer_minutes": 0,
    }
    defaults.update(overrides)
    return defaults


# ──────────── Package ────────────
def create_package_payload(**overrides) -> dict:
    defaults = {
        "tier": "GOLD",
        "per_head_cents": 15_000,
        "fb_minimum_cents": 2_000_000,
        "service_charge_pct": 0.22,
        "tax_pct": 0.08,
    }
    defaults.update(overrides)
    return defaults


# ──────────── Coordinator ────────────
def create_coordinator_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dana Coordinator",
        "active_booking_cap": 8,
    }
    defaults.update(overrides)
    return defaults


# ──────────── Client ────────────
def create_client_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Pat Client",
        "email": unique_email(),
    }
    defaults.update(overrides)
    return defaults


# ──────────── Booking ────────────
def create_booking_payload(client_id: str, venue_id: str, package_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "venue_id": venue_id,
        "package_id": package_id,
        "event_date": EVENT_DATE,
        "ceremony_start": CEREMONY_START,
        "ceremony_end": CEREMONY_END,
        "reception_start": RECEPTION_START,
        "reception_end": RECEPTION_END,
        "expected_guest_count": 120,
    }
    defaults.update(overrides)
    return defaults


# ──────────── SpaceHold ────────────
def create_hold_payload(space_id: str, block_role: str, expected_booking_version: int, **overrides) -> dict:
    defaults = {
        "space_id": space_id,
        "block_role": block_role,
        "expected_booking_version": expected_booking_version,
    }
    defaults.update(overrides)
    return defaults


# ──────────── Payment ────────────
def create_payment_payload(direction: str, amount_cents: int, method: str = "ACH", **overrides) -> dict:
    defaults = {
        "direction": direction,
        "amount_cents": amount_cents,
        "method": method,
    }
    defaults.update(overrides)
    return defaults


# ──────────── Vendor ────────────
def create_vendor_payload(company_name: str = "Bloom Co", vendor_role: str = "FLORAL", **overrides) -> dict:
    defaults = {
        "company_name": company_name,
        "vendor_role": vendor_role,
    }
    defaults.update(overrides)
    return defaults


# ──────────── COI upload ────────────
def create_coi_payload(coi_expires_on: str, **overrides) -> dict:
    defaults = {"coi_expires_on": coi_expires_on}
    defaults.update(overrides)
    return defaults


# ──────────── Guarantee ────────────
def create_guarantee_payload(guaranteed_count: int, **overrides) -> dict:
    defaults = {"guaranteed_count": guaranteed_count}
    defaults.update(overrides)
    return defaults


# ──────────── Walkthrough ────────────
def create_walkthrough_payload(scheduled_start: str, scheduled_end: str, **overrides) -> dict:
    defaults = {
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


# ──────────── RescheduleRequest ────────────
def create_reschedule_payload(
    reason_kind: str,
    proposed_event_date: str,
    proposed_ceremony_start: str,
    proposed_ceremony_end: str,
    proposed_reception_start: str,
    proposed_reception_end: str,
    **overrides,
) -> dict:
    defaults = {
        "reason_kind": reason_kind,
        "proposed_event_date": proposed_event_date,
        "proposed_ceremony_start": proposed_ceremony_start,
        "proposed_ceremony_end": proposed_ceremony_end,
        "proposed_reception_start": proposed_reception_start,
        "proposed_reception_end": proposed_reception_end,
    }
    defaults.update(overrides)
    return defaults


# ──────────── Counter ────────────
def create_counter_payload(
    proposed_event_date: str,
    proposed_ceremony_start: str,
    proposed_ceremony_end: str,
    proposed_reception_start: str,
    proposed_reception_end: str,
    **overrides,
) -> dict:
    defaults = {
        "proposed_event_date": proposed_event_date,
        "proposed_ceremony_start": proposed_ceremony_start,
        "proposed_ceremony_end": proposed_ceremony_end,
        "proposed_reception_start": proposed_reception_start,
        "proposed_reception_end": proposed_reception_end,
    }
    defaults.update(overrides)
    return defaults
