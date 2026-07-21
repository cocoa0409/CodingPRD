"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _assert_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only entity must NOT carry updated_at"
    assert "version" not in data, "append-only entity must NOT carry version"


def assert_host(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["email"], str)
    assert data["payout_method"] in ("BANK", "PAYPAL")
    assert isinstance(data["pending_payout_cents"], int)
    assert isinstance(data["paid_out_cents"], int)
    assert isinstance(data["completed_stays_count"], int)


def assert_guest(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["wallet_credit_cents"], int)


def assert_listing(data: dict):
    _assert_common(data)
    assert data["site_type"] in ("YURT", "CABIN", "TREEHOUSE", "DOME", "AIRSTREAM")
    assert data["status"] in ("DRAFT", "PENDING_PERMIT", "LISTED", "SUSPENDED", "DELISTED")
    assert data["cancellation_policy"] in ("FLEXIBLE", "MODERATE", "STRICT")
    assert isinstance(data["max_guests"], int) and data["max_guests"] >= 1
    assert isinstance(data["min_nights"], int) and data["min_nights"] >= 1
    assert isinstance(data["reserved_nights_count"], int)


def assert_permit(data: dict):
    _assert_common(data)
    assert data["permit_type"] in ("CAMPING", "STRUCTURE", "SPECIAL_USE")
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")


def assert_seasonal_rate(data: dict):
    _assert_common(data)
    assert isinstance(data["nightly_rate_cents"], int) and data["nightly_rate_cents"] >= 0


def assert_add_on(data: dict):
    _assert_common(data)
    assert data["category"] in ("AMENITY", "EXPERIENCE")
    assert data["pricing_unit"] in ("PER_STAY", "PER_NIGHT", "PER_GUEST")
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_experience_slot(data: dict):
    _assert_common(data)
    assert isinstance(data["max_participants"], int) and data["max_participants"] >= 1
    assert isinstance(data["reserved_participants"], int)


def assert_booking(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "REQUESTED", "CONFIRMED", "CHECKED_IN", "COMPLETED", "DECLINED", "CANCELLED"
    )
    assert data["payment_status"] in ("PENDING", "PAID", "REFUNDED", "PARTIALLY_REFUNDED")
    assert isinstance(data["nights"], int) and data["nights"] >= 1
    assert isinstance(data["add_ons"], list)


def assert_payout(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "PAID", "PARTIAL", "VOIDED")
    assert isinstance(data["estimated_amount_cents"], int)


def assert_review(data: dict):
    _assert_append_only(data)
    assert isinstance(data["rating"], int) and 1 <= data["rating"] <= 5


def assert_message(data: dict):
    _assert_append_only(data)
    assert data["sender_role"] in ("HOST", "GUEST")
