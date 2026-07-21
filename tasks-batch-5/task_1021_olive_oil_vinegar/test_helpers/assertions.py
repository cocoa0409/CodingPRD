"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime, timezone
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_instant(s: str) -> datetime:
    """Parse an ISO 8601 UTC string to an aware datetime, tolerating a trailing
    'Z' and any number of fractional-second digits. PRD pins the computed instant,
    not its exact rendering, so instant equality is the faithful comparison."""
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str):
    """Assert two ISO 8601 timestamps denote the same UTC instant, independent of
    fractional-digit rendering (PRD is silent on the format of derived date fields
    such as best_by_date and tasting start_at)."""
    assert is_iso8601_timestamp(actual), f"not an ISO 8601 timestamp: {actual!r}"
    assert _parse_instant(actual) == _parse_instant(expected), \
        f"expected instant {expected}, got {actual}"


def assert_common_fields(data: dict):
    """Full common-field set: id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_member(data: dict):
    assert_common_fields(data)
    assert data["member_type"] in ("RETAIL", "WHOLESALE")
    assert data["wallet_credit_cents"] >= 0, "wallet_credit_cents must never be negative"
    assert data["loyalty_points"] >= 0, "loyalty_points must never be negative"
    assert isinstance(data["allergen_restrictions"], list)


def assert_product(data: dict):
    assert_common_fields(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert data["product_type"] in (
        "BULK_OIL", "BULK_VINEGAR", "BOTTLE", "ACCESSORY", "GIFT_SET", "BLEND")
    assert isinstance(data["allergens"], list)


def assert_product_component(data: dict):
    """ProductComponent is lightweight (PRD §2.4): id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "component id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "version" not in data, "ProductComponent must not expose version"
    assert "updated_at" not in data, "ProductComponent must not expose updated_at"


def assert_fusti(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("IN_SERVICE", "LOW", "QUARANTINED", "EMPTY", "RETIRED")
    assert data["current_volume_ml"] >= 0, "current_volume_ml never negative"
    assert data["reserved_volume_ml"] >= 0, "reserved_volume_ml never negative"
    assert data["available_volume_ml"] == data["current_volume_ml"] - data["reserved_volume_ml"], \
        "available_volume_ml == current - reserved"


def assert_order(data: dict):
    assert_common_fields(data)
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert data["fulfillment_status"] in ("PENDING", "RESERVED", "FULFILLED", "CANCELLED")
    assert data["provisional_subtotal_cents"] >= 0
    assert data["provisional_total_cents"] >= 0


def assert_reservation(data: dict):
    """Reservation is a ledger row read only for status/links (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "reservation id must be a UUID"
    assert data["status"] in ("HELD", "COMMITTED", "RELEASED")


def assert_wholesale_account(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "APPROVED", "REJECTED", "SUSPENDED")
    assert data["tier"] in ("NONE", "TIER_1", "TIER_2", "TIER_3")


def assert_subscription(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "PAUSED", "CANCELLED")
    assert data["renewals_count"] >= 0


def assert_tasting_session(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("BOOKED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW")
