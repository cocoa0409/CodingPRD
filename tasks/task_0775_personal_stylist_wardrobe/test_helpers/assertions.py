"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0
    assert isinstance(data["has_paid_invoice"], bool)
    assert data["status"] == "ACTIVE"


def assert_stylist(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert 0 <= data["commission_pct"] <= 1
    assert data["tier"] in ("JUNIOR", "SENIOR", "LEAD")
    assert isinstance(data["earned_commission_cents"], int)
    assert data["status"] == "ACTIVE"


def assert_assessment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["client_id"])
    assert data["color_palette"] in ("WARM", "COOL", "NEUTRAL")
    assert data["budget_band"] in ("ECONOMY", "MID", "PREMIUM", "LUXURY")
    assert data["status"] in ("DRAFT", "COMPLETED")


def assert_engagement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["stylist_id"])
    assert data["mode"] in ("HOURLY", "PACKAGE")
    assert isinstance(data["block_rate_cents"], int) and data["block_rate_cents"] > 0
    assert data["status"] in ("DRAFT", "ACTIVE", "FULFILLED", "CANCELLED")
    assert isinstance(data["retail_spend_cents"], int) and data["retail_spend_cents"] >= 0


def assert_package_hours_conserved(data: dict):
    """PACKAGE invariant: package_blocks == available + reserved + consumed."""
    assert data["mode"] == "PACKAGE", "conservation invariant only applies to PACKAGE engagements"
    total = (data["hours_available_blocks"] + data["hours_reserved_blocks"]
             + data["hours_consumed_blocks"])
    assert total == data["package_blocks"], (
        f"conservation broken: package_blocks={data['package_blocks']} != "
        f"available({data['hours_available_blocks']}) + reserved({data['hours_reserved_blocks']}) "
        f"+ consumed({data['hours_consumed_blocks']}) = {total}"
    )
    assert data["hours_available_blocks"] >= 0
    assert data["hours_reserved_blocks"] >= 0
    assert data["hours_consumed_blocks"] >= 0


def assert_session(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["engagement_id"])
    assert data["session_type"] in ("CLOSET_AUDIT", "SHOPPING", "VIRTUAL", "EVENT")
    assert data["modality"] in ("IN_PERSON", "VIRTUAL")
    assert data["status"] in ("SCHEDULED", "CONFIRMED", "COMPLETED", "CANCELLED")
    assert data["charge_variant"] in ("PROVISIONAL", "FINAL")
    assert isinstance(data["estimated_blocks"], int) and data["estimated_blocks"] >= 4
    assert isinstance(data["charge_cents"], int) and data["charge_cents"] >= 0


def assert_purchase_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["session_id"])
    assert isinstance(data["retail_cost_cents"], int) and data["retail_cost_cents"] > 0
    assert isinstance(data["marked_up_price_cents"], int) and data["marked_up_price_cents"] > 0
    assert isinstance(data["commission_cents"], int) and data["commission_cents"] >= 0
    assert data["status"] in ("PURCHASED", "RETURNED")


def assert_lookbook(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["engagement_id"])
    assert isinstance(data["outfit_count"], int) and data["outfit_count"] >= 0
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert data["status"] in ("DRAFT", "DELIVERED", "ACCEPTED")


def assert_subscription(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["client_id"])
    assert data["tier"] in ("SILVER", "GOLD")
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] > 0
    assert data["refresh_credits_remaining"] >= 0
    assert data["status"] in ("PENDING", "ACTIVE", "CANCELLED")


def assert_referral(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["referrer_client_id"])
    assert isinstance(data["estimated_credit_cents"], int)
    assert isinstance(data["realized_credit_cents"], int)
    assert data["status"] in ("PENDING", "SIGNED_UP", "CREDITED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["engagement_id"])
    assert isinstance(data["subtotal_cents"], int) and data["subtotal_cents"] >= 0
    assert isinstance(data["styling_fee_cents"], int) and data["styling_fee_cents"] >= 0
    assert isinstance(data["volume_discount_cents"], int) and data["volume_discount_cents"] >= 0
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert data["status"] in ("ISSUED", "PAID")
