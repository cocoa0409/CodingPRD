"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive integer"


def assert_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["lifecycle_status"] in [
        "DRAFT", "PUBLISHED", "REGISTRATION_OPEN", "REGISTRATION_LOCKED",
        "JUDGING", "TABULATING", "FINALIZED", "CLOSED",
    ]
    assert data["weather_posture"] in ["NORMAL", "WATCH", "POSTPONED", "CANCELLED"]
    assert data["sound_permit_status"] in ["ACTIVE", "SUSPENDED"]
    assert data["tabulation_method"] in ["STRAIGHT_AVERAGE", "DROP_EXTREMES"]
    assert isinstance(data["treasury_cents"], int)
    assert isinstance(data["noise_exceedance_count"], int)


def assert_show_class(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["min_year"], int) and isinstance(data["max_year"], int)
    assert data["min_year"] <= data["max_year"]
    assert data["judging_mode"] in ["JUDGED", "PEOPLES_CHOICE", "BOTH"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert 1 <= data["award_depth"] <= 3
    assert isinstance(data["confirmed_count"], int) and data["confirmed_count"] >= 0


def assert_zone(data: dict):
    _assert_common_fields(data)
    assert data["zone_type"] in ["SHOW_FIELD", "OVERFLOW", "VENDOR_ROW"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["assigned_count"], int) and data["assigned_count"] >= 0


def assert_registrant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]


def assert_vehicle(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["year"], int)
    assert isinstance(data["make"], str) and data["make"]
    assert isinstance(data["model"], str) and data["model"]


def assert_registration(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "PENDING_PAYMENT", "CONFIRMED", "CHECKED_IN", "COMPLETED",
        "WITHDRAWN", "REFUND_REQUESTED", "REFUNDED", "NO_SHOW",
    ]
    assert data["pricing_tier"] in ["PREREG", "DAY_OF"]
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert isinstance(data["paid_cents"], int) and data["paid_cents"] >= 0
    assert isinstance(data["refunded_cents"], int) and data["refunded_cents"] >= 0


def assert_payment(data: dict):
    """Payment is an append-only ledger row: id + created_at, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only Payment must not carry updated_at"
    assert "version" not in data, "append-only Payment must not carry version"
    assert data["kind"] in ["ENTRY_FEE", "BOOTH_FEE", "REFUND"]
    assert data["method"] in ["CASH", "CARD", "CHECK"]
    assert data["status"] == "SUCCEEDED"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_waiver(data: dict):
    """Waiver is immutable once created: id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "immutable Waiver must not carry updated_at"
    assert "version" not in data, "immutable Waiver must not carry version"
    assert isinstance(data["signature_name"], str) and data["signature_name"]
    assert is_iso8601_timestamp(data.get("signed_at", "")), "signed_at must be ISO 8601"


def assert_noise_reading(data: dict):
    """NoiseReading is a sampled measurement: id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "NoiseReading must not carry updated_at"
    assert "version" not in data, "NoiseReading must not carry version"
    assert data["source"] in ["STAGE", "PA_SYSTEM", "EXHAUST", "CROWD"]
    assert isinstance(data["is_curfew"], bool)
    assert isinstance(data["is_exceedance"], bool)


def assert_booth_application(data: dict):
    _assert_common_fields(data)
    assert data["booth_tier"] in ["SINGLE", "DOUBLE", "SPONSOR"]
    assert data["status"] in ["SUBMITTED", "APPROVED", "REJECTED", "PAID", "ASSIGNED", "CANCELLED"]
    assert isinstance(data["paid_cents"], int) and data["paid_cents"] >= 0


def assert_judge(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["assigned_class_ids"], list)
    assert isinstance(data["submitted_sheet_count"], int) and data["submitted_sheet_count"] >= 0


def assert_score_sheet(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "LOCKED"]
    assert isinstance(data["criteria_scores"], list) and len(data["criteria_scores"]) == 5
    for item in data["criteria_scores"]:
        assert item["criterion"] in ["EXTERIOR", "INTERIOR", "ENGINE", "AUTHENTICITY", "CONDITION"]
        assert isinstance(item["points"], int) and 0 <= item["points"] <= 10


def assert_ballot(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["VALID", "VOID"]
    assert data["weight"] in [1, 2]


def assert_award(data: dict):
    _assert_common_fields(data)
    assert data["award_kind"] in ["CLASS_PLACE", "PEOPLES_CHOICE", "BEST_OF_SHOW"]
    assert data["status"] in ["PENDING", "COMPUTED", "FINALIZED", "PRESENTED"]
    assert isinstance(data["overridden"], bool)


def assert_sound_slot(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["SCHEDULED", "CANCELLED", "COMPLETED"]
    assert isinstance(data["performer_name"], str) and data["performer_name"]
