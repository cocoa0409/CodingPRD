"""Entity assertions for the Racquet Club API.

Each assert_{entity}() validates the response structure against the PRD contract
(common audit fields per §2.4, plus each entity's own fields).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_court(data: dict):
    _assert_common(data)
    assert data["surface"] in ("HARD", "CLAY", "GRASS")
    assert data["location_type"] in ("INDOOR", "OUTDOOR")
    assert data["status"] in ("AVAILABLE", "MAINTENANCE", "RETIRED")
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0


def assert_plan(data: dict):
    _assert_common(data)
    assert data["tier"] in ("BASIC", "PREMIER", "ELITE")
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["monthly_court_credits"], int) and data["monthly_court_credits"] >= 0


def assert_member(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0
    assert isinstance(data["account_balance_cents"], int)


def assert_subscription(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "FROZEN", "CANCELLED")
    assert isinstance(data["court_credits_remaining"], int)
    assert data["court_credits_remaining"] >= 0
    assert isinstance(data["freeze_count"], int) and data["freeze_count"] >= 0


def assert_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in ("BOOKED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW")
    assert isinstance(data["provisional_fee_cents"], int)
    assert isinstance(data["credits_used"], int) and data["credits_used"] >= 0
    assert isinstance(data["is_peak"], bool)


def assert_pro(data: dict):
    _assert_common(data)
    assert data["status"] == "ACTIVE"
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0


def assert_lesson(data: dict):
    _assert_common(data)
    assert data["kind"] in ("PRIVATE", "CLINIC")
    assert data["status"] in ("SCHEDULED", "CONFIRMED", "COMPLETED", "CANCELLED")
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0


def assert_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in ("ENROLLED", "WAITLISTED", "CANCELLED")


def assert_competition(data: dict):
    _assert_common(data)
    assert data["format"] in ("ROUND_ROBIN", "LADDER", "TOURNAMENT")
    assert data["status"] in ("REGISTRATION", "IN_PROGRESS", "COMPLETED")


def assert_participant(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "ELIMINATED")
    assert isinstance(data["wins"], int) and isinstance(data["losses"], int)


def assert_stringing_job(data: dict):
    _assert_common(data)
    assert data["status"] in ("RECEIVED", "IN_PROGRESS", "READY", "PICKED_UP", "CANCELLED")
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
