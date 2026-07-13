"""Payload factories — one per entity, input fields only."""
from .constants import TIER_DEFAULTS


def create_dock_payload(**overrides) -> dict:
    payload = {
        "name": "Home",
        "location_code": "HM",
        "capacity": 10,
    }
    payload.update(overrides)
    return payload


def create_tier_payload(tier_code: str = "SAIL", **overrides) -> dict:
    base = dict(TIER_DEFAULTS[tier_code])
    payload = {"tier_code": tier_code, **base}
    payload.update(overrides)
    return payload


def create_boat_payload(dock_id: str, boat_type: str = "PONTOON", **overrides) -> dict:
    payload = {"dock_id": dock_id, "boat_type": boat_type}
    payload.update(overrides)
    return payload


def create_member_payload(
    membership_tier: str,
    home_dock_id: str,
    full_name: str = "A",
    email: str = "a@x.com",
    **overrides,
) -> dict:
    payload = {
        "full_name": full_name,
        "email": email,
        "membership_tier": membership_tier,
        "home_dock_id": home_dock_id,
    }
    payload.update(overrides)
    return payload


def create_reservation_payload(
    member_id: str,
    dock_id: str,
    boat_type: str,
    start_time: str,
    end_time: str,
    **overrides,
) -> dict:
    payload = {
        "member_id": member_id,
        "dock_id": dock_id,
        "boat_type": boat_type,
        "start_time": start_time,
        "end_time": end_time,
    }
    payload.update(overrides)
    return payload


def create_training_session_payload(
    dock_id: str,
    session_type: str,
    start_time: str,
    end_time: str,
    capacity: int = 5,
    instructor_name: str = "I",
    **overrides,
) -> dict:
    payload = {
        "dock_id": dock_id,
        "session_type": session_type,
        "start_time": start_time,
        "end_time": end_time,
        "capacity": capacity,
        "instructor_name": instructor_name,
    }
    payload.update(overrides)
    return payload


def create_enrollment_payload(member_id: str, session_id: str, **overrides) -> dict:
    payload = {"member_id": member_id, "session_id": session_id}
    payload.update(overrides)
    return payload


def create_damage_report_payload(
    reservation_id: str,
    boat_id: str,
    severity: str,
    repair_cost_cents: int,
    **overrides,
) -> dict:
    payload = {
        "reservation_id": reservation_id,
        "boat_id": boat_id,
        "severity": severity,
        "repair_cost_cents": repair_cost_cents,
    }
    payload.update(overrides)
    return payload


def create_dues_invoice_payload(
    period_start: str,
    period_end: str,
    expected_member_version: int,
    **overrides,
) -> dict:
    payload = {
        "period_start": period_start,
        "period_end": period_end,
        "expected_member_version": expected_member_version,
    }
    payload.update(overrides)
    return payload
