"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be >= 1"


def _assert_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only record must not carry version"
    assert "updated_at" not in data, "append-only record must not carry updated_at"


def assert_user(data: dict):
    _assert_common(data)
    assert data["verification_status"] in (
        "UNVERIFIED", "PENDING", "VERIFIED", "REJECTED"
    ), f"unexpected verification_status {data.get('verification_status')!r}"
    assert isinstance(data["trust_score"], int)
    assert 0 <= data["trust_score"] <= 500, "trust_score must be clamped to [0,500]"
    assert isinstance(data["rating_count"], int)
    assert isinstance(data["late_return_count"], int)
    assert isinstance(data["upheld_claim_count"], int)
    assert isinstance(data["total_earnings_cents"], int)


def assert_listing(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED")
    assert data["declared_value_cents"] > 0
    assert data["base_daily_rate_cents"] > 0
    assert data["deposit_cents"] >= 0
    assert data["quantity"] >= 1
    assert 5000 <= data["demand_multiplier_bps"] <= 30000
    assert data["active_booking_count"] >= 0


def assert_booking(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "REQUESTED", "APPROVED", "DECLINED", "CANCELLED", "ACTIVE",
        "EXTENSION_REQUESTED", "RETURNED", "LATE", "COMPLETED",
    )
    assert isinstance(data["billable_days"], int)
    assert isinstance(data["rental_subtotal_cents"], int)
    assert isinstance(data["renter_service_fee_cents"], int)
    assert isinstance(data["provisional_total_cents"], int)


def assert_handoff(data: dict):
    _assert_common(data)
    assert data["type"] in ("PICKUP", "RETURN")
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_deposit(data: dict):
    _assert_common(data)
    assert data["status"] in ("HELD", "PARTIALLY_CAPTURED", "CAPTURED", "RELEASED")
    assert_deposit_conserved(data)


def assert_deposit_conserved(data: dict):
    """PRD §2.10 conservation invariant: held + captured + released == original_amount."""
    total = data["held_cents"] + data["captured_cents"] + data["released_cents"]
    assert total == data["original_amount_cents"], (
        f"deposit not conserved: {data['held_cents']}+{data['captured_cents']}+"
        f"{data['released_cents']} != {data['original_amount_cents']}"
    )
    assert data["held_cents"] >= 0 and data["captured_cents"] >= 0 and data["released_cents"] >= 0


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "APPROVED", "PARTIALLY_APPROVED", "DENIED")
    assert data["claim_type"] in ("DAMAGE", "LOSS")


def assert_payout(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "HELD", "RELEASED")


def assert_verification(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED")
    assert data["document_type"] in ("PASSPORT", "DRIVERS_LICENSE", "NATIONAL_ID")


def assert_condition_report(data: dict):
    _assert_append_only(data)
    assert data["phase"] in ("PICKUP", "RETURN")
    assert isinstance(data["photo_urls"], list) and len(data["photo_urls"]) >= 1


def assert_rating(data: dict):
    _assert_append_only(data)
    assert 1 <= data["score"] <= 5
    assert data["direction"] in ("RENTER_TO_OWNER", "OWNER_TO_RENTER")
