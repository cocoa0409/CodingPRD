"""Payload factories — one per input surface, input fields only."""

from .constants import DEFAULT_CHART

_email_counter = {"n": 0}


def _unique_email(prefix: str = "owner") -> str:
    _email_counter["n"] += 1
    return f"{prefix}{_email_counter['n']}@example.com"


def create_member_payload(**overrides) -> dict:
    """POST /club/members — full_name, email, owned_points (PRD §3.1)."""
    defaults = {
        "full_name": "Test Owner",
        "email": _unique_email(),
        "owned_points": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_resort_payload(**overrides) -> dict:
    """POST /club/resorts — name, region (PRD §3.3)."""
    defaults = {"name": "Test Resort", "region": "FL"}
    defaults.update(overrides)
    return defaults


def create_unit_type_payload(**overrides) -> dict:
    """POST /club/resorts/{id}/unit-types — name, total_units, seasonal chart (PRD §3.3)."""
    defaults = {
        "name": "2BR Villa",
        "total_units": 1,
        **DEFAULT_CHART,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(
    member_id: str, unit_type_id: str, points_bucket_id: str, check_in: str, check_out: str, **overrides
) -> dict:
    """POST /club/reservations (PRD §3.4)."""
    payload = {
        "member_id": member_id,
        "unit_type_id": unit_type_id,
        "points_bucket_id": points_bucket_id,
        "check_in": check_in,
        "check_out": check_out,
    }
    payload.update(overrides)
    return payload


def create_waitlist_payload(
    member_id: str, unit_type_id: str, points_bucket_id: str, check_in: str, check_out: str, **overrides
) -> dict:
    """POST /club/waitlist-entries (PRD §3.7)."""
    payload = {
        "member_id": member_id,
        "unit_type_id": unit_type_id,
        "points_bucket_id": points_bucket_id,
        "check_in": check_in,
        "check_out": check_out,
    }
    payload.update(overrides)
    return payload


def create_guest_certificate_payload(**overrides) -> dict:
    """POST /club/reservations/{id}/guest-certificates — guest_name (PRD §3.6)."""
    defaults = {"guest_name": "Guest Name"}
    defaults.update(overrides)
    return defaults


def create_listing_payload(listing_type: str = "RENTAL", **overrides) -> dict:
    """POST /club/reservations/{id}/listings — listing_type, ask_amount_cents? (PRD §3.6)."""
    payload = {"listing_type": listing_type}
    payload.update(overrides)
    return payload


def generate_statement_payload(expected_member_version: int, **overrides) -> dict:
    """POST /club/members/{id}/statements — expected_member_version, special_assessment_cents? (PRD §3.9)."""
    payload = {"expected_member_version": expected_member_version}
    payload.update(overrides)
    return payload


def pay_statement_payload(amount_cents: int, **overrides) -> dict:
    """POST /club/statements/{id}/pay — amount_cents (PRD §3.9)."""
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_transfer_payload(from_member_id: str, to_member_id: str, points: int, **overrides) -> dict:
    """POST /club/transfers (PRD §3.8)."""
    payload = {
        "from_member_id": from_member_id,
        "to_member_id": to_member_id,
        "points": points,
    }
    payload.update(overrides)
    return payload


def accept_transfer_payload(outcome: str = "ACCEPT", **overrides) -> dict:
    """POST /club/transfers/{id}/accept — outcome ACCEPT|REJECT (PRD §3.8)."""
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def bank_payload(points: int, **overrides) -> dict:
    """POST /club/points-buckets/{id}/bank — points (PRD §3.2)."""
    payload = {"points": points}
    payload.update(overrides)
    return payload


def borrow_payload(points: int, **overrides) -> dict:
    """POST /club/points-buckets/{id}/borrow — points (PRD §3.2)."""
    payload = {"points": points}
    payload.update(overrides)
    return payload
