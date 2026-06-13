"""Entity assertions for the Promotion Coupon Engine."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_customer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["display_name"], str)
    assert isinstance(data["order_count"], int)
    assert isinstance(data["lifetime_discount_cents"], int)
    assert isinstance(data.get("version"), int)


def assert_segment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str)
    assert isinstance(data["member_count"], int)
    assert isinstance(data.get("version"), int)


def assert_segment_membership(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a valid UUID"
    assert is_valid_uuid(data.get("segment_id", "")), "segment_id must be a valid UUID"
    assert data["status"] in ("ACTIVE", "REVOKED")


def assert_promotion(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["name"], str)
    assert data["promo_type"] in ("PERCENT_OFF", "BOGO", "THRESHOLD")
    assert data["stacking_class"] in ("EXCLUSIVE", "STACKABLE")
    assert data["eligibility_mode"] in ("ALL", "SEGMENT", "FIRST_ORDER")
    assert data["status"] in ("DRAFT", "ACTIVE", "PAUSED", "EXHAUSTED", "EXPIRED", "ARCHIVED")
    assert isinstance(data["budget_consumed_cents"], int)
    assert data["budget_consumed_cents"] >= 0
    assert isinstance(data.get("version"), int)


def assert_coupon(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("promotion_id", "")), "promotion_id must be a valid UUID"
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["use_mode"] in ("SINGLE_USE", "MULTI_USE")
    assert isinstance(data["redeemed_count"], int)
    assert data["redeemed_count"] >= 0
    assert data["status"] in ("ENABLED", "DISABLED", "EXHAUSTED")
    assert isinstance(data.get("version"), int)


def assert_blackout_window(data: dict):
    """BlackoutWindow is immutable configuration: id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("promotion_id", "")), "promotion_id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("starts_at", "")), "starts_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("ends_at", "")), "ends_at must be ISO 8601"


def assert_exclusion_rule(data: dict):
    """ExclusionRule is immutable configuration: id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("promotion_a_id", "")), "promotion_a_id must be a valid UUID"
    assert is_valid_uuid(data.get("promotion_b_id", "")), "promotion_b_id must be a valid UUID"


def assert_cart(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a valid UUID"
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["total_discount_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] >= 0, "total_cents floored at 0"
    assert data["pricing_status"] in ("UNPRICED", "PRICED", "STALE")
    assert data["checkout_status"] in ("OPEN", "LOCKED", "CHECKED_OUT", "ABANDONED")
    assert isinstance(data.get("version"), int)


def assert_cart_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("cart_id", "")), "cart_id must be a valid UUID"
    assert isinstance(data["sku"], str)
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["line_total_cents"], int)


def assert_cart_application(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("cart_id", "")), "cart_id must be a valid UUID"
    assert is_valid_uuid(data.get("promotion_id", "")), "promotion_id must be a valid UUID"
    assert data["source"] in ("MANUAL", "AUTO_APPLY")
    assert data["status"] in ("APPLIED", "REMOVED")
    assert isinstance(data["raw_discount_cents"], int)
    assert isinstance(data["discount_cents"], int)


def assert_coupon_redemption(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("promotion_id", "")), "promotion_id must be a valid UUID"
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a valid UUID"
    assert is_valid_uuid(data.get("cart_id", "")), "cart_id must be a valid UUID"
    assert isinstance(data["discount_cents"], int)
    assert data["status"] in ("RESERVED", "CONFIRMED", "RELEASED")
