"""Payload factories — one per create/mutation endpoint, input fields only."""
import itertools

_email_seq = itertools.count(1)


def unique_email(prefix: str = "member") -> str:
    return f"{prefix}{next(_email_seq)}@example.com"


def create_member_payload(**overrides) -> dict:
    """Required: name, email, tier. Optional: max_active_loans, max_active_holds,
    balance_limit_cents, membership_expires_at (PRD §3.1)."""
    payload = {
        "name": "Test Member",
        "email": unique_email(),
        "tier": "BASIC",
    }
    payload.update(overrides)
    return payload


def create_volunteer_payload(**overrides) -> dict:
    """Required: name, role_level. Optional: active (PRD §3.1)."""
    payload = {
        "name": "Test Volunteer",
        "role_level": "VOLUNTEER",
    }
    payload.update(overrides)
    return payload


def create_item_payload(**overrides) -> dict:
    """Required: name, category, replacement_value_cents, loan_period_days,
    daily_late_fee_cents. Optional: max_renewals (PRD §3.2)."""
    payload = {
        "name": "Cordless Drill 18V",
        "category": "TOOL",
        "replacement_value_cents": 12000,
        "loan_period_days": 7,
        "daily_late_fee_cents": 100,
    }
    payload.update(overrides)
    return payload


def add_copy_payload(**overrides) -> dict:
    """Required: asset_tag, acquired_on. Optional: origin (PRD §3.2)."""
    payload = {
        "asset_tag": "TAG-1",
        "acquired_on": "2025-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_reservation_payload(member_id, item_id, window_start, window_end, **overrides) -> dict:
    """Required: member_id, item_id, window_start, window_end (PRD §3.3)."""
    payload = {
        "member_id": member_id,
        "item_id": item_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def create_loan_payload(member_id, copy_id, expected_item_version, reservation_id=None, **overrides) -> dict:
    """Required: member_id, copy_id, expected_item_version. Optional: reservation_id (PRD §3.4)."""
    payload = {
        "member_id": member_id,
        "copy_id": copy_id,
        "expected_item_version": expected_item_version,
    }
    if reservation_id is not None:
        payload["reservation_id"] = reservation_id
    payload.update(overrides)
    return payload


def return_loan_payload(return_condition="GOOD", **overrides) -> dict:
    """Required: return_condition (PRD §3.5)."""
    payload = {"return_condition": return_condition}
    payload.update(overrides)
    return payload


def create_hold_payload(member_id, item_id, **overrides) -> dict:
    """Required: member_id, item_id (PRD §3.7)."""
    payload = {"member_id": member_id, "item_id": item_id}
    payload.update(overrides)
    return payload


def create_donation_payload(item_id, **overrides) -> dict:
    """Required: donor_name, item_id, proposed_condition. Optional: donor_member_id (PRD §3.2)."""
    payload = {
        "donor_name": "Anonymous Donor",
        "item_id": item_id,
        "proposed_condition": "GOOD",
    }
    payload.update(overrides)
    return payload


def accept_donation_payload(asset_tag="DON-1", **overrides) -> dict:
    """Required: asset_tag. Optional: acquired_on (PRD §3.2)."""
    payload = {"asset_tag": asset_tag}
    payload.update(overrides)
    return payload


def reject_donation_payload(**overrides) -> dict:
    """Optional: reason (PRD §3.2)."""
    payload = {}
    payload.update(overrides)
    return payload


def create_ticket_payload(copy_id, reason="ROUTINE", **overrides) -> dict:
    """Required: copy_id, reason. Optional: severity, scheduled_start, scheduled_end (PRD §3.8)."""
    payload = {"copy_id": copy_id, "reason": reason}
    payload.update(overrides)
    return payload


def resolve_ticket_payload(outcome="RETURN_TO_SERVICE", **overrides) -> dict:
    """Required: outcome (PRD §3.8)."""
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def waive_fee_payload(**overrides) -> dict:
    """Optional: reason (PRD §3.9)."""
    payload = {}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601: str) -> dict:
    """Required: to_iso8601 (PRD §2.5)."""
    return {"to_iso8601": to_iso8601}
