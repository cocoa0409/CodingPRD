"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_location(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in ["OPEN", "CLOSED"]
    assert isinstance(data["open_minute_of_day"], int)
    assert isinstance(data["close_minute_of_day"], int)
    assert isinstance(data["no_show_fee_cents"], int)
    assert isinstance(data["cancel_window_hours"], int)
    assert isinstance(data["flexologist_buffer_minutes"], int)


def assert_flexologist(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in ["ACTIVE", "INACTIVE"]
    assert isinstance(data["certified_intro"], bool)


def assert_table(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ["ACTIVE", "OUT_OF_SERVICE"]


def assert_service(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["kind"] in ["ASSISTED_STRETCH", "RECOVERY", "INTRO"]
    assert data["status"] in ["ACTIVE", "RETIRED"]
    assert data["duration_minutes"] > 0
    assert data["credit_cost"] >= 0
    assert data["list_price_cents"] >= 0


def assert_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["intro_completed"], bool)
    assert data["mobility_tier"] in [None, "FOUNDATION", "INTERMEDIATE", "ADVANCED"]
    assert isinstance(data["strike_score"], int)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_membership(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["tier"] in ["STARTER", "PLUS", "PRO"]
    assert data["status"] in ["ACTIVE", "FROZEN", "CANCELLED"]
    assert isinstance(data["version"], int)
    assert_wallet_invariants(data, granted_basis="granted_credits")


def assert_credit_pack(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ["ACTIVE", "DEPLETED", "EXPIRED"]
    assert data["pack_credits"] > 0
    assert_wallet_invariants(data, granted_basis="pack_credits")


def assert_wallet_invariants(data: dict, granted_basis: str):
    """held/consumed/available are whole integers; available floored at 0
    and never exceeds the granted basis."""
    held = data["held_credits"]
    consumed = data["consumed_credits"]
    available = data["available_credits"]
    granted = data[granted_basis]
    assert isinstance(held, int) and held >= 0, "held_credits must be a non-negative int"
    assert isinstance(consumed, int) and consumed >= 0, "consumed_credits must be a non-negative int"
    assert isinstance(available, int) and available >= 0, "available_credits floored at 0"
    assert available == max(0, granted - held - consumed), (
        f"available_credits must equal max(0, {granted_basis} - held - consumed)"
    )


def assert_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["schedule_status"] in [
        "REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED", "LATE_CANCELLED", "NO_SHOW"
    ]
    assert data["credit_status"] in ["HELD", "CONSUMED", "RELEASED", "FORFEITED"]
    assert data["funding_source"] in ["MEMBERSHIP", "CREDIT_PACK"]
    assert isinstance(data["is_intro"], bool)
    assert isinstance(data["fee_charged_cents"], int)


def assert_recurring_series(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ["DRAFT", "ACTIVE", "ENDED"]
    assert isinstance(data["generated_count"], int)
    assert isinstance(data["skipped_count"], int)


def assert_addon(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["kind"] in ["COMPRESSION", "PERCUSSION"]
    assert isinstance(data["voided"], bool)


def assert_no_version_fields(data: dict):
    """Append-only resources (AddOn, NoShowEvent, ClockState) must NOT expose
    updated_at or version."""
    assert "updated_at" not in data, "append-only resource must not expose updated_at"
    assert "version" not in data, "append-only resource must not expose version"
