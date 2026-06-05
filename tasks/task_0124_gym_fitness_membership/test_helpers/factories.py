"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import PLAN_PLUS

_email_counter = itertools.count(1)


def unique_email(prefix: str = "member") -> str:
    """A process-unique email; the server enforces uniqueness across non-archived members."""
    return f"{prefix}_{next(_email_counter)}@example.com"


def create_membership_plan_payload(**overrides) -> dict:
    defaults = dict(PLAN_PLUS)
    defaults.update(overrides)
    return defaults


def create_location_payload(**overrides) -> dict:
    defaults = {"name": "Downtown", "occupancy_cap": 50}
    defaults.update(overrides)
    return defaults


def create_member_payload(plan_id: str, home_location_id: str, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "home_location_id": home_location_id,
        "full_name": "Test Member",
        "email": unique_email(),
        "period_start": "2026-06-10T00:00:00Z",
        "period_end": "2026-07-01T00:00:00Z",
        "due_date": "2026-06-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_class_session_payload(location_id: str, **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "title": "Spin",
        "starts_at": "2026-06-20T09:00:00Z",
        "ends_at": "2026-06-20T10:00:00Z",
        "capacity": 5,
        "waitlist_cap": 5,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(session_id: str, member_id: str, expected_session_version: int, **overrides) -> dict:
    defaults = {
        "session_id": session_id,
        "member_id": member_id,
        "expected_session_version": expected_session_version,
    }
    defaults.update(overrides)
    return defaults


def create_pt_package_payload(member_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "sessions_purchased": 5,
        "list_price_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_pt_session_payload(package_id: str, expected_package_version: int, **overrides) -> dict:
    defaults = {
        "package_id": package_id,
        "trainer_name": "Trainer",
        "starts_at": "2026-06-25T15:00:00Z",
        "expected_package_version": expected_package_version,
    }
    defaults.update(overrides)
    return defaults


def create_dues_invoice_payload(member_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "period_start": "2026-07-01T00:00:00Z",
        "period_end": "2026-08-01T00:00:00Z",
        "due_date": "2026-07-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_guest_pass_payload(member_id: str, location_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "guest_name": "Pat Guest",
        "location_id": location_id,
    }
    defaults.update(overrides)
    return defaults


def create_member_check_in_payload(member_id: str, location_id: str, **overrides) -> dict:
    defaults = {"member_id": member_id, "location_id": location_id}
    defaults.update(overrides)
    return defaults


def create_guest_check_in_payload(guest_pass_id: str, location_id: str, **overrides) -> dict:
    defaults = {"guest_pass_id": guest_pass_id, "location_id": location_id}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
