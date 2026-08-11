"""Entity assertions and domain invariant checkers.

Each assert_<entity>() checks the PRD-guaranteed shape: UUID id, ISO 8601
timestamps, status enum membership, and the presence/type of declared fields.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_customer(data: dict):
    _assert_common_fields(data, "Customer")
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["climate_zone"] in ("COOL", "TRANSITION", "WARM")
    assert isinstance(data["referral_code"], str) and data["referral_code"]
    assert isinstance(data["credit_balance_cents"], int)
    assert data["credit_balance_cents"] >= 0, "credit balance never goes negative"
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CHURNED")


def assert_lawn(data: dict):
    _assert_common_fields(data, "LawnProfile")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["label"], str)
    assert isinstance(data["lawn_size_sqm"], int) and data["lawn_size_sqm"] > 0
    assert data["grass_type"] in ("COOL_SEASON", "WARM_SEASON", "MIXED")
    assert isinstance(data["region"], str)
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_soil_test(data: dict):
    _assert_common_fields(data, "SoilTestKit")
    assert is_valid_uuid(data.get("lawn_id", ""))
    assert data["status"] in ("KIT_SHIPPED", "SAMPLE_RETURNED", "ANALYZED")
    assert isinstance(data["reship_count"], int) and data["reship_count"] >= 0


def assert_plan(data: dict):
    _assert_common_fields(data, "PlanVersion")
    assert is_valid_uuid(data.get("lawn_id", ""))
    assert is_valid_uuid(data.get("soil_test_id", ""))
    assert isinstance(data["season_year"], int)
    assert isinstance(data["plan_lines"], list)
    assert data["status"] in ("DRAFT", "PENDING_REVIEW", "ACTIVE", "SUPERSEDED")
    assert isinstance(data["provisional_value_cents"], int)


def assert_subscription(data: dict):
    _assert_common_fields(data, "Subscription")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("plan_id", ""))
    assert data["billing_cycle"] in ("MONTHLY", "ANNUAL")
    assert isinstance(data["auto_ship"], bool)
    assert data["status"] in ("ACTIVE", "PAUSED", "PAST_DUE", "CANCELLED")
    assert isinstance(data["skips_used_in_window"], int)


def assert_shipment(data: dict):
    _assert_common_fields(data, "ShipmentBox")
    assert is_valid_uuid(data.get("subscription_id", ""))
    assert data["box_kind"] in ("SEASONAL", "ADDON", "REPLACEMENT")
    assert data["fulfillment_status"] in (
        "SCHEDULED", "PICKING", "SHIPPED", "DELIVERED", "HELD", "SKIPPED", "CANCELLED"
    )
    assert data["billing_status"] in ("PENDING", "INVOICED", "PAID", "FAILED", "VOID")
    assert isinstance(data["lines"], list)
    assert isinstance(data["provisional_charge_cents"], int)


def assert_application(data: dict):
    _assert_common_fields(data, "ApplicationTask")
    assert is_valid_uuid(data.get("subscription_id", ""))
    assert is_valid_uuid(data.get("shipment_id", ""))
    assert isinstance(data["product_sku"], str)
    assert isinstance(data["scheduled_date"], str)
    assert data["status"] in (
        "AWAITING_DELIVERY", "SCHEDULED", "FROZEN", "APPLIED", "CANCELLED"
    )
    assert isinstance(data["snooze_count"], int) and data["snooze_count"] >= 0


def assert_weather_advisory(data: dict):
    _assert_common_fields(data, "WeatherAdvisory")
    assert isinstance(data["region"], str)
    assert isinstance(data["date"], str)
    assert isinstance(data["rain_probability"], (int, float))
    assert isinstance(data["wind_kph"], int)
    assert isinstance(data["temp_high_c"], int)


def assert_add_on(data: dict):
    _assert_common_fields(data, "AddOnOrder")
    assert is_valid_uuid(data.get("subscription_id", ""))
    assert isinstance(data["add_on_sku"], str)
    assert isinstance(data["qty_units"], int) and data["qty_units"] > 0
    assert data["status"] in ("QUOTED", "CONFIRMED", "FULFILLED", "CANCELLED", "EXPIRED")
    assert isinstance(data["quoted_price_cents"], int)


def assert_claim(data: dict):
    _assert_common_fields(data, "SatisfactionClaim")
    assert is_valid_uuid(data.get("subscription_id", ""))
    assert is_valid_uuid(data.get("shipment_id", ""))
    assert data["claim_reason"] in ("INEFFECTIVE", "DAMAGED", "WRONG_PRODUCT", "OTHER")
    assert data["status"] in ("FILED", "RESOLVED", "DENIED")


def assert_referral(data: dict):
    _assert_common_fields(data, "Referral")
    assert is_valid_uuid(data.get("referrer_customer_id", ""))
    assert is_valid_uuid(data.get("referee_customer_id", ""))
    assert isinstance(data["referral_code_used"], str)
    assert data["status"] in ("PENDING", "QUALIFIED", "REVOKED")
    assert isinstance(data["provisional_credit_cents"], int)


def assert_invoice(data: dict):
    _assert_common_fields(data, "Invoice")
    assert is_valid_uuid(data.get("subscription_id", ""))
    assert is_valid_uuid(data.get("shipment_id", ""))
    assert isinstance(data["line_items"], list)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["credit_applied_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["status"] in ("ISSUED", "PAID", "FAILED", "VOID")


def assert_ledger_entry(data: dict):
    """Append-only entry: id + created_at only; NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", "")), "CreditLedgerEntry.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "CreditLedgerEntry.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "ledger entries must not expose updated_at"
    assert "version" not in data, "ledger entries must not expose version"
    assert data["entry_type"] in (
        "EARN_REFERRAL", "REVOKE_REFERRAL", "EARN_SATISFACTION",
        "REDEEM_INVOICE", "RESTORE_VOID_INVOICE", "ADJUSTMENT",
    )
    assert isinstance(data["amount_cents"], int)


def assert_catalog_product(data: dict):
    _assert_common_fields(data, "CatalogProduct")
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["category"] in ("FERTILIZER", "WEED", "PEST", "SEED", "SOIL_AMENDMENT")
    assert isinstance(data["list_price_cents"], int)
    assert isinstance(data["tier_t1_cents"], int)
    assert isinstance(data["tier_t2_cents"], int)
    assert isinstance(data["tier_t3_cents"], int)
    assert isinstance(data["window_start_md"], str)
    assert isinstance(data["window_end_md"], str)


def assert_ledger_sum_equals_balance(entries: list, balance: int):
    """credit_balance_cents always equals the sum of the customer's entries."""
    total = sum(e["amount_cents"] for e in entries)
    assert total == balance, (
        f"ledger sum {total} must equal credit_balance_cents {balance}"
    )
