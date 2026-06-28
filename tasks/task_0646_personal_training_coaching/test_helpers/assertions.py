"""Entity assertions and domain invariant checkers.

Per-entity assert_{entity}() validate the response structure against the PRD
contract; invariant checkers verify cross-field rules that must always hold.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_full_resource_envelope(data: dict):
    """Full resources carry id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_envelope(data: dict):
    """Append-only records carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_trainer(data: dict):
    _assert_full_resource_envelope(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["status"] in ("ACTIVE", "DEACTIVATED")


def assert_client(data: dict):
    _assert_full_resource_envelope(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["sex"] in ("MALE", "FEMALE")
    assert data["intake_status"] in ("DRAFT", "SUBMITTED", "ASSESSED")
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0
    assert data["booking_privilege"] in ("ALLOWED", "SUSPENDED")


def assert_engagement(data: dict):
    _assert_full_resource_envelope(data)
    assert data["billing_model"] in ("SESSION_PACK", "ONLINE_SUBSCRIPTION")
    assert data["status"] in ("ACTIVE", "PAUSED", "ENDED")
    assert data["pause_reason"] in ("NONE", "PACK_DEPLETED", "MANUAL")
    assert_wallet_never_negative(data)


def assert_wallet_never_negative(data: dict):
    """PRD §2.8: wallet_credit_cents accumulates refunds and is never negative."""
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["wallet_credit_cents"] >= 0, "wallet_credit_cents must never go negative"


def assert_session_pack(data: dict):
    _assert_full_resource_envelope(data)
    assert data["status"] in ("ACTIVE", "DEPLETED", "REFUNDED")
    assert isinstance(data["total_sessions"], int)
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["per_session_value_cents"], int)
    assert isinstance(data["sessions_committed"], int)
    assert isinstance(data["sessions_remaining"], int)
    assert_pack_seat_conservation(data)


def assert_pack_seat_conservation(data: dict):
    """PRD §3.3: total_sessions == sessions_committed + sessions_remaining."""
    assert (data["total_sessions"]
            == data["sessions_committed"] + data["sessions_remaining"]), (
        "total_sessions must equal sessions_committed + sessions_remaining")


def assert_booking(data: dict):
    _assert_full_resource_envelope(data)
    assert data["status"] in (
        "BOOKED", "COMPLETED", "CANCELLED", "LATE_CANCELLED", "NO_SHOW", "RESCHEDULED")
    assert is_iso8601_timestamp(data["start_utc"]), "start_utc must be ISO 8601"
    assert is_iso8601_timestamp(data["end_utc"]), "end_utc must be ISO 8601"
    assert isinstance(data["fee_charged_cents"], int)


def assert_program_assignment(data: dict):
    _assert_full_resource_envelope(data)
    assert data["status"] in ("DRAFT", "PUBLISHED", "ARCHIVED")
    assert isinstance(data["planned_workouts_per_week"], int)
    assert isinstance(data["habit_checks_target"], int)


def assert_macro_plan(data: dict):
    _assert_full_resource_envelope(data)
    assert data["status"] in ("PROVISIONAL", "LOCKED")
    assert data["goal"] in ("FAT_LOSS", "MAINTENANCE", "MUSCLE_GAIN")
    assert data["activity_level"] in ("SEDENTARY", "MODERATE", "ACTIVE")
    assert isinstance(data["target_calories"], int)
    assert isinstance(data["protein_g"], int)
    assert isinstance(data["carb_g"], int)
    assert isinstance(data["fat_g"], int)


def assert_check_in(data: dict):
    _assert_full_resource_envelope(data)
    assert data["status"] in ("SUBMITTED", "REVISION_REQUESTED", "ASSESSED")
    assert isinstance(data["adherence_score"], int)
    assert 0 <= data["adherence_score"] <= 100, "adherence_score must be 0..100"


def assert_habit_log(data: dict):
    _assert_append_only_envelope(data)
    assert data["kind"] in ("WORKOUT_COMPLETED", "NUTRITION_LOGGED", "HABIT_CHECK")


def assert_message(data: dict):
    _assert_append_only_envelope(data)
    assert data["sender_role"] in ("TRAINER", "CLIENT")
    assert isinstance(data["body"], str) and len(data["body"]) > 0
