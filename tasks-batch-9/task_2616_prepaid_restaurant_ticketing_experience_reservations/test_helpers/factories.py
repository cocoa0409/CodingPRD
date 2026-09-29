"""
Request-payload builders for the Prepaid Restaurant Ticketing API.

Each builder produces a valid payload for one create or action endpoint and
lets a caller override any field. Unique names and emails are generated where
the PRD requires uniqueness: a restaurant `name` "unique across all
restaurants", a guest `email` "unique across all guests", a table `table_code`
"unique within that restaurant", a package and an add-on `name` each "unique
within the restaurant".
"""

import itertools
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short suffix that makes a uniqueness-constrained field unique."""
    return f"{next(_counter):05d}"


# ─── temporal helpers ─────────────────────────────────────────────────────


def iso(instant: datetime) -> str:
    """Render a datetime as an ISO 8601 UTC instant with a trailing Z."""
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating fractional seconds."""
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def shift(value: str, *, minutes: int = 0, hours: int = 0, seconds: int = 0) -> str:
    """An instant offset from ``value`` by the given amount."""
    return iso(
        parse_iso(value)
        + timedelta(minutes=minutes, hours=hours, seconds=seconds)
    )


def hours_before(instant: str, hours: float) -> str:
    """The instant exactly ``hours`` before ``instant``, to the second."""
    return iso(parse_iso(instant) - timedelta(hours=hours))


def minutes_before(instant: str, minutes: int) -> str:
    return iso(parse_iso(instant) - timedelta(minutes=minutes))


def minutes_after(instant: str, minutes: int) -> str:
    return iso(parse_iso(instant) + timedelta(minutes=minutes))


# ─── entity payload builders ──────────────────────────────────────────────


def restaurant_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "name": f"Aurum {unique_suffix()}",
        "service_charge_bp": 725,
        "hold_ttl_minutes": 20,
        "offer_ttl_minutes": 15,
        "max_offer_rounds": 2,
        "max_name_changes": 1,
        "name_change_cutoff_minutes": 240,
        "transfer_cutoff_minutes": 1440,
        "max_transfers_per_guest": 2,
        "no_show_grace_minutes": 30,
        "goodwill_credit_cap_cents": 20000,
        "prep_lead_minutes": 45,
        "refund_scrutiny_threshold_cents": 300000,
    }
    payload.update(overrides)
    return payload


def guest_payload(**overrides: Any) -> Dict[str, Any]:
    suffix = unique_suffix()
    payload = {
        "email": f"guest{suffix}@aurum.test",
        "display_name": f"Guest {suffix}",
    }
    payload.update(overrides)
    return payload


def table_payload(restaurant_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "restaurant_id": restaurant_id,
        "table_code": f"T{unique_suffix()}",
        "seats_min": 1,
        "seats_max": 8,
        "turn_buffer_minutes": 15,
    }
    payload.update(overrides)
    return payload


def package_payload(restaurant_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "restaurant_id": restaurant_id,
        "name": f"Tasting Menu {unique_suffix()}",
        "course_count": 8,
        "base_price_cents": 12000,
        "prepayment_mode": "DEPOSIT",
        "deposit_bp": 3000,
        "forfeiture_schedule_code": "STANDARD",
        "forfeiture_basis": "DEPOSIT_BASIS",
        "release_discount_bp": 1500,
        "kitchen_prep_minutes_per_cover": 12,
        "min_party_size": 1,
        "max_party_size": 8,
    }
    payload.update(overrides)
    return payload


def add_on_payload(restaurant_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "restaurant_id": restaurant_id,
        "name": f"Add On {unique_suffix()}",
        "price_cents": 4500,
        "prep_minutes_per_unit": 0,
        "max_qty_per_cover": 2,
        "order_cutoff_minutes": 120,
        "requires_kitchen_ack": False,
    }
    payload.update(overrides)
    return payload


def service_payload(restaurant_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "restaurant_id": restaurant_id,
        "service_date": "2026-09-10",
        "meal_period": "DINNER",
        "seating_start_utc": "2026-09-10T22:00:00Z",
        "seating_end_utc": "2026-09-11T02:00:00Z",
        "turn_time_minutes": 150,
        "seats_capacity": 20,
        "demand_tier": "STANDARD",
        "unsold_release_bp": 5000,
        "release_lead_minutes": 180,
        "waitlist_policy": "FAIR_QUEUE",
        "kitchen_prep_capacity_minutes": 600,
    }
    payload.update(overrides)
    return payload


def ticket_class_payload(
    service_id: str, package_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "service_id": service_id,
        "package_id": package_id,
        "seats_allocated": 20,
        "min_party_size": 1,
        "max_party_size": 8,
    }
    payload.update(overrides)
    return payload


def reservation_payload(
    ticket_class_id: str,
    guest_id: str,
    expected_ticket_class_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "ticket_class_id": ticket_class_id,
        "guest_id": guest_id,
        "party_size": 2,
        "primary_guest_name": "Primary Guest",
        "expected_ticket_class_version": expected_ticket_class_version,
    }
    payload.update(overrides)
    return payload


def add_on_line_payload(
    add_on_id: str, expected_reservation_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "add_on_id": add_on_id,
        "qty": 1,
        "expected_reservation_version": expected_reservation_version,
    }
    payload.update(overrides)
    return payload


def dietary_note_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "guest_index": 1,
        "restriction_code": "NUT",
        "severity": "ALLERGY",
        "note_text": "No nuts of any kind.",
    }
    payload.update(overrides)
    return payload


def ack_payload(decision: str = "ACCEPT", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def reject_payload(
    reject_reason_code: str = "CROSS_CONTAMINATION_RISK", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": "REJECT",
        "reject_reason_code": reject_reason_code,
    }
    payload.update(overrides)
    return payload


def amend_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "restriction_code": "GLUTEN",
        "severity": "INFO",
        "note_text": "Amended note.",
    }
    payload.update(overrides)
    return payload


def waitlist_entry_payload(
    service_id: str, guest_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "service_id": service_id,
        "guest_id": guest_id,
        "party_size": 2,
    }
    payload.update(overrides)
    return payload


def refund_exception_payload(
    reservation_id: str, requested_cents: int, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "reservation_id": reservation_id,
        "reason_code": "MEDICAL",
        "requested_cents": requested_cents,
    }
    payload.update(overrides)
    return payload


def decide_payload(
    decision: str = "APPROVED",
    approved_cents: int = None,
    decision_note_code: str = "POLICY_EXCEPTION",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": decision,
        "decision_note_code": decision_note_code,
    }
    if approved_cents is not None:
        payload["approved_cents"] = approved_cents
    payload.update(overrides)
    return payload


def goodwill_credit_payload(
    refund_exception_id: str,
    issued_cents: int,
    expires_at_utc: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "refund_exception_id": refund_exception_id,
        "issued_cents": issued_cents,
        "expires_at_utc": expires_at_utc,
    }
    payload.update(overrides)
    return payload


def redemption_payload(
    reservation_id: str,
    amount_cents: int,
    expected_goodwill_credit_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "reservation_id": reservation_id,
        "amount_cents": amount_cents,
        "expected_goodwill_credit_version": expected_goodwill_credit_version,
    }
    payload.update(overrides)
    return payload


def assign_table_payload(
    table_id: str, seat_from_utc: str, **overrides: Any
) -> Dict[str, Any]:
    payload = {"table_id": table_id, "seat_from_utc": seat_from_utc}
    payload.update(overrides)
    return payload


def transfer_payload(recipient_guest_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"recipient_guest_id": recipient_guest_id}
    payload.update(overrides)
    return payload


def name_change_payload(primary_guest_name: str = "Renamed Guest") -> Dict[str, Any]:
    return {"primary_guest_name": primary_guest_name}


def payment_payload(amount_cents: int) -> Dict[str, Any]:
    return {"amount_cents": amount_cents}


def demand_tier_payload(demand_tier: str) -> Dict[str, Any]:
    return {"demand_tier": demand_tier}
