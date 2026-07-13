"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_tunnel(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in ("OPERATIONAL", "MAINTENANCE")


def assert_instructor(data: dict):
    _assert_common(data)
    assert data["cert_level"] in ("L1", "L2", "L3")
    assert data["tier"] in ("JUNIOR", "SENIOR")
    assert isinstance(data["sessions_completed"], int)


def assert_member(data: dict):
    _assert_common(data)
    assert data["experience_status"] in ("FIRST_TIME", "RETURNING")
    assert data["membership_tier"] in ("NONE", "STANDARD", "PRO")
    assert isinstance(data["health_flags"], list)
    for counter in (
        "reflight_credit_minutes", "total_credits_minted", "total_credits_consumed",
        "wallet_cents", "confirmed_booking_count", "outstanding_addon_cents",
    ):
        assert isinstance(data[counter], int), f"{counter} must be an integer"


def assert_booking(data: dict):
    _assert_common(data)
    assert data["booking_type"] in ("WALK_IN", "RESERVATION")
    assert data["status"] in ("CONFIRMED", "EXHAUSTED", "CANCELLED", "COMPLETED")
    assert isinstance(data["total_price_cents"], int)
    assert isinstance(data["minutes_included"], int)
    assert isinstance(data["minutes_remaining"], int)
    assert data["minutes_remaining"] >= 0, "minutes_remaining never goes negative"


def assert_session(data: dict):
    _assert_common(data)
    assert data["op_status"] in ("OPEN", "RUNNING", "CLOSED", "CANCELLED")
    assert data["staffing_status"] in ("UNSTAFFED", "STAFFED")
    assert isinstance(data["seats_taken"], int)
    assert isinstance(data["seats_available"], int)
    assert data["seats_available"] >= 0, "seats_available never goes negative"


def assert_flight(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "SCHEDULED", "CHECKED_IN", "FLOWN", "ABORTED", "NO_SHOW", "CANCELLED",
    )
    assert isinstance(data["scheduled_minutes"], int)
    assert isinstance(data["minutes_charged"], int)
    assert isinstance(data["reflight_credit_granted"], int)


def assert_seat_conservation(session: dict):
    """PRD §2.5: seats_taken + seats_available == capacity, always."""
    assert session["seats_taken"] + session["seats_available"] == session["capacity"], (
        f"seat conservation broken: {session['seats_taken']} + "
        f"{session['seats_available']} != {session['capacity']}"
    )


def assert_minute_conservation(booking: dict, consumed: int):
    """PRD §2.5: minutes_remaining + consumed == minutes_included, always."""
    assert booking["minutes_remaining"] + consumed == booking["minutes_included"], (
        f"minute conservation broken: {booking['minutes_remaining']} + {consumed} "
        f"!= {booking['minutes_included']}"
    )
