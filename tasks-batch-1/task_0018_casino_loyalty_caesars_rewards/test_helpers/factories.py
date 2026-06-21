"""Payload factories — one per entity, input fields only.

Only `source: input` fields are populated. Computed fields and system-set
fields are server-managed.
"""


def create_property_payload(
    name: str = "Caesars Palace LV",
    market_segment: str = "VEGAS_STRIP",
    base_room_rate_cents: int = 30000,
    **overrides,
) -> dict:
    payload = {
        "name": name,
        "market_segment": market_segment,
        "base_room_rate_cents": base_room_rate_cents,
    }
    payload.update(overrides)
    return payload


def create_member_payload(
    home_property_id: str,
    full_name: str = "Test Member",
    email: str = "test@example.com",
    **overrides,
) -> dict:
    payload = {
        "full_name": full_name,
        "email": email,
        "home_property_id": home_property_id,
    }
    payload.update(overrides)
    return payload


def create_host_payload(
    home_property_id: str,
    employee_email: str = "host@caesars.example",
    **overrides,
) -> dict:
    payload = {
        "employee_email": employee_email,
        "home_property_id": home_property_id,
    }
    payload.update(overrides)
    return payload


def create_gaming_session_payload(
    member_id: str,
    property_id: str,
    started_at: str = "2026-01-01T10:00:00Z",
    ended_at: str = "2026-01-01T11:00:00Z",
    game_type: str = "SLOTS",
    theoretical_loss_cents: int = 100000,
    **overrides,
) -> dict:
    payload = {
        "member_id": member_id,
        "property_id": property_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "game_type": game_type,
        "theoretical_loss_cents": theoretical_loss_cents,
    }
    payload.update(overrides)
    return payload


def create_comp_room_booking_payload(
    member_id: str,
    property_id: str,
    expected_member_version: int,
    check_in: str = "2026-02-01T15:00:00Z",
    check_out: str = "2026-02-02T11:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "member_id": member_id,
        "property_id": property_id,
        "check_in": check_in,
        "check_out": check_out,
        "expected_member_version": expected_member_version,
    }
    payload.update(overrides)
    return payload


def create_host_assignment_payload(
    member_id: str,
    host_id: str,
    expected_member_version: int,
    **overrides,
) -> dict:
    payload = {
        "member_id": member_id,
        "host_id": host_id,
        "expected_member_version": expected_member_version,
    }
    payload.update(overrides)
    return payload


def create_self_exclusion_payload(
    member_id: str,
    exclusion_until: str = "2027-01-01T00:00:00Z",
    reason: str = "Test self-exclusion",
    **overrides,
) -> dict:
    payload = {
        "member_id": member_id,
        "exclusion_until": exclusion_until,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


def create_annual_reset_run_payload(
    reset_year: int = 2027,
    scheduled_for: str = "2028-01-01T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "reset_year": reset_year,
        "scheduled_for": scheduled_for,
    }
    payload.update(overrides)
    return payload
