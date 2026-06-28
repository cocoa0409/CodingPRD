"""Entity assertions and domain invariant checkers for the Blow-Dry Bar API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Every primary resource carries id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 and increments per mutation"


def assert_style_service(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["base_duration_minutes"], int)
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["blowout_credit_cost"], int) and data["blowout_credit_cost"] >= 0
    assert isinstance(data["active"], bool)


def assert_add_on(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["category"] in ("UPDO", "BRAID", "EXTENSION")
    assert isinstance(data["extra_duration_minutes"], int)
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["discount_eligible"], bool)
    assert isinstance(data["active"], bool)


def assert_membership_plan(data: dict):
    _assert_common(data)
    assert data["tier"] in ("BASIC", "PLUS", "VIP")
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["included_blowout_credits"], int)
    assert 0 <= data["member_discount_pct"] <= 1


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["blowout_credit_balance"], int)
    assert data["blowout_credit_balance"] >= 0, "blowout_credit_balance never negative"
    assert isinstance(data["prepay_balance_cents"], int)
    assert data["prepay_balance_cents"] >= 0, "prepay_balance_cents never negative"
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0


def assert_stylist(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["commission_tier"] in ("JUNIOR", "SENIOR", "MASTER")
    assert isinstance(data["shift_start_minute"], int)
    assert isinstance(data["shift_end_minute"], int)
    assert data["shift_end_minute"] > data["shift_start_minute"]
    assert isinstance(data["earned_commission_cents"], int)
    assert isinstance(data["earned_tips_cents"], int)
    assert isinstance(data["active"], bool)


def assert_chair(data: dict):
    _assert_common(data)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert isinstance(data["open_minute"], int)
    assert isinstance(data["close_minute"], int)
    assert data["close_minute"] > data["open_minute"]
    assert isinstance(data["turnover_buffer_minutes"], int)
    assert isinstance(data["active"], bool)


def assert_appointment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["chair_id"])
    assert is_valid_uuid(data["stylist_id"])
    assert is_valid_uuid(data["style_service_id"])
    assert data["payment_method"] in ("CREDIT", "PREPAY")
    assert data["lifecycle_status"] in (
        "BOOKED", "CHECKED_IN", "IN_SERVICE", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert data["settlement_status"] in ("UNSETTLED", "SETTLED", "VOIDED")
    assert data["end_minute"] == data["start_minute"] + data["scheduled_duration_minutes"]
    assert isinstance(data["service_charge_cents"], int)
    assert isinstance(data["credits_applied"], int) and data["credits_applied"] >= 0


def assert_event_block(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["organizer_member_id"])
    assert data["block_type"] in ("GROUP", "BRIDAL")
    assert data["status"] in ("HOLD", "CONFIRMED", "CHECKED_IN", "CLOSED", "CANCELLED")
    assert data["window_end_minute"] > data["window_start_minute"]
    assert isinstance(data["reserved_chair_ids"], list)
    assert 2 <= data["party_size"] <= 20
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert isinstance(data["deposit_paid_cents"], int) and data["deposit_paid_cents"] >= 0


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["stock_qty"], int) and data["stock_qty"] >= 0
    assert 0 <= data["retail_commission_pct"] <= 1


def assert_retail_sale(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["gross_cents"], int) and data["gross_cents"] >= 0
    assert isinstance(data["retail_commission_cents"], int)
    assert data["status"] in ("SOLD", "VOIDED")


def assert_package_purchase(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["credits_purchased"], int) and data["credits_purchased"] >= 1
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert data["status"] in ("ACTIVE", "REFUNDED")


def assert_commission_house_conserved(data: dict):
    """PRD §3.10: commission_amount_cents + house_amount_cents == service_charge_cents."""
    assert data["commission_amount_cents"] + data["house_amount_cents"] == \
        data["service_charge_cents"], "commission + house must sum to the service charge"


def assert_tip_split_conserved(data: dict):
    """PRD §3.10: stylist_tip_cents + tip_pool_cents == tip_cents (pool is exact remainder)."""
    assert data["stylist_tip_cents"] + data["tip_pool_cents"] == data["tip_cents"], \
        "stylist tip + pool tip must sum to the captured tip exactly"
