"""Entity-shape assertions and domain invariant checkers."""

from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating a trailing Z and any number of
    fractional-second digits."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant(actual, expected) -> None:
    """Compare two UTC instants by value, so 12:00:00Z and 12:00:00.000Z match."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"expected instant {expected}, got {actual}"
    )


def assert_system_fields(data: dict, *, versioned: bool = True) -> None:
    """Every row carries a UUID id and an ISO 8601 created_at; every row except
    an Offer also carries updated_at and an integer version starting at 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC: {data.get('created_at')!r}"
    )
    if versioned:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"updated_at must be ISO 8601 UTC: {data.get('updated_at')!r}"
        )
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"version must be a positive integer, got {data.get('version')!r}"
        )


def assert_seller_account(data: dict) -> None:
    assert_system_fields(data)
    for field in ("legal_name", "tax_id", "state_code", "contact_email"):
        assert isinstance(data[field], str) and data[field], f"{field} must be non-empty"
    assert len(data["state_code"]) == 2, "state_code must be a two-letter code"
    assert data["account_status"] in ("ACTIVE", "MANIFEST_PROBATION", "SUSPENDED")
    assert data["commission_tier"] in ("TIER_STANDARD", "TIER_PREFERRED", "TIER_PROBATION")
    for field in ("commission_rate_bps", "gross_hammer_cents", "listed_retail_value_cents",
                  "net_proceeds_cents", "sold_retail_value_cents", "scored_lot_count"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    for field in ("gross_recovery_rate", "net_recovery_rate", "manifest_accuracy_avg"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"


def assert_buyer_account(data: dict) -> None:
    assert_system_fields(data)
    for field in ("legal_name", "tax_id", "state_code", "contact_email"):
        assert isinstance(data[field], str) and data[field], f"{field} must be non-empty"
    assert data["qualification_status"] in ("PENDING", "QUALIFIED", "REJECTED", "SUSPENDED")
    assert data["business_verification_status"] in ("UNVERIFIED", "VERIFIED", "REJECTED")
    for field in ("approved_credit_limit_cents", "outstanding_exposure_cents",
                  "wallet_credit_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer"
        )


def assert_warehouse(data: dict) -> None:
    assert_system_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert len(data["state_code"]) == 2
    assert isinstance(data["dock_door_count"], int) and data["dock_door_count"] >= 1
    assert isinstance(data["turnaround_buffer_minutes"], int)
    assert data["turnaround_buffer_minutes"] >= 0


def assert_carrier(data: dict) -> None:
    assert_system_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["scac_code"], str) and data["scac_code"]
    assert isinstance(data["daily_pickup_capacity"], int) and data["daily_pickup_capacity"] >= 1


def assert_brand_policy(data: dict) -> None:
    assert_system_fields(data)
    assert isinstance(data["brand_code"], str) and data["brand_code"]
    assert isinstance(data["permitted_channels"], list) and data["permitted_channels"]


def assert_lot(data: dict) -> None:
    assert_system_fields(data)
    assert is_valid_uuid(data["seller_id"]), "seller_id must be a UUID"
    assert is_valid_uuid(data["warehouse_id"]), "warehouse_id must be a UUID"
    assert data["category_code"] in ("APPAREL", "ELECTRONICS", "HOME_GOODS", "TOYS")
    assert data["condition_grade"] in ("NEW_OVERSTOCK", "CUSTOMER_RETURNS", "SALVAGE")
    assert data["lot_status"] in (
        "DRAFT", "MANIFEST_IN_REVIEW", "MANIFEST_APPROVED", "MANIFEST_REJECTED",
        "LISTED", "SOLD", "RELIST_PENDING", "VOIDED",
    )
    for field in ("manifest_line_count", "declared_unit_count",
                  "declared_retail_value_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer"
        )


def assert_manifest_line(data: dict) -> None:
    assert_system_fields(data)
    assert is_valid_uuid(data["lot_id"]), "lot_id must be a UUID"
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["unit_count"], int) and data["unit_count"] >= 1
    assert isinstance(data["unit_retail_cents"], int) and data["unit_retail_cents"] >= 1
    assert data["declared_condition"] in ("NEW", "LIKE_NEW", "USED_GOOD", "DAMAGED", "SALVAGE")
    assert data["line_status"] in ("ACTIVE", "VOIDED")


def assert_listing(data: dict) -> None:
    assert_system_fields(data)
    assert is_valid_uuid(data["lot_id"]), "lot_id must be a UUID"
    assert data["listing_format"] in ("AUCTION", "FIXED_PRICE", "NEGOTIATED")
    assert data["resale_channel"] in (
        "MARKETPLACE_RESALE", "EXPORT_ONLY", "DISCOUNT_RETAIL", "SCRAP_ONLY"
    )
    assert data["listing_status"] in ("DRAFT", "OPEN", "CLOSED_SOLD", "CLOSED_NO_SALE")
    assert is_iso8601_timestamp(data["window_start_at"])
    assert is_iso8601_timestamp(data["window_end_at"])
    assert is_iso8601_timestamp(data["effective_close_at"])
    assert isinstance(data["extension_count"], int) and data["extension_count"] >= 0
    assert isinstance(data["bid_count"], int) and data["bid_count"] >= 0
    assert isinstance(data["reserve_met"], bool)


def assert_bid(data: dict) -> None:
    assert_system_fields(data)
    assert is_valid_uuid(data["listing_id"]) and is_valid_uuid(data["buyer_id"])
    assert data["bid_type"] in ("LIVE", "PROXY")
    assert data["bid_status"] in ("STANDING", "WINNING", "SUPERSEDED", "WON", "LOST")
    assert isinstance(data["ceiling_cents"], int) and data["ceiling_cents"] >= 1
    assert is_iso8601_timestamp(data["placed_at"])
    assert isinstance(data["meets_reserve"], bool)


def assert_negotiation(data: dict) -> None:
    assert_system_fields(data)
    assert is_valid_uuid(data["listing_id"]) and is_valid_uuid(data["buyer_id"])
    assert data["negotiation_status"] in (
        "AWAITING_SELLER", "AWAITING_BUYER", "ACCEPTED", "DECLINED"
    )
    assert isinstance(data["round_number"], int) and 1 <= data["round_number"] <= 4


def assert_offer(data: dict) -> None:
    """An Offer is append-only: it carries id and created_at but neither
    updated_at nor version."""
    assert_system_fields(data, versioned=False)
    assert is_valid_uuid(data["negotiation_id"]), "negotiation_id must be a UUID"
    assert data["offer_side"] in ("BUYER", "SELLER")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert is_iso8601_timestamp(data["expires_at"])
    assert "version" not in data, "an Offer row must not carry a version field"
    assert "updated_at" not in data, "an Offer row must not carry an updated_at field"


def assert_sale_order(data: dict) -> None:
    assert_system_fields(data)
    assert is_valid_uuid(data["listing_id"]) and is_valid_uuid(data["buyer_id"])
    assert data["sale_source"] in (
        "AUCTION_CLOSE", "FIXED_PRICE_PURCHASE", "NEGOTIATED_ACCEPTANCE"
    )
    assert data["payment_status"] in ("UNPAID", "PARTIALLY_PAID", "PAID", "REFUND_ISSUED")
    assert data["logistics_status"] in (
        "AWAITING_APPOINTMENT", "APPOINTMENT_SCHEDULED", "PICKED_UP", "ABANDONED"
    )
    assert data["settlement_basis"] in ("PROVISIONAL", "FINAL")
    for field in ("hammer_price_cents", "buyer_premium_bps", "buyer_premium_cents",
                  "pallet_count", "estimated_freight_cents", "pre_fee_total_cents",
                  "total_due_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer number of cents"
    assert is_iso8601_timestamp(data["payment_due_at"])
    assert is_iso8601_timestamp(data["pickup_deadline_at"])
    assert_money_invariants(data)


def assert_pickup_appointment(data: dict) -> None:
    assert_system_fields(data)
    assert is_valid_uuid(data["sale_order_id"])
    assert is_valid_uuid(data["warehouse_id"]) and is_valid_uuid(data["carrier_id"])
    assert data["appointment_status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert isinstance(data["dock_door_number"], int) and data["dock_door_number"] >= 1
    assert is_iso8601_timestamp(data["window_start_at"])
    assert is_iso8601_timestamp(data["window_end_at"])
    assert isinstance(data["bol_number"], str) and data["bol_number"]


def assert_claim(data: dict) -> None:
    assert_system_fields(data)
    assert is_valid_uuid(data["sale_order_id"]) and is_valid_uuid(data["manifest_line_id"])
    assert data["claim_type"] in ("UNIT_SHORTAGE", "CONDITION_MISGRADE", "MISSING_SKU")
    assert isinstance(data["claimed_units"], int) and data["claimed_units"] >= 1
    assert data["claim_status"] in (
        "SUBMITTED", "UNDER_REVIEW", "EVIDENCE_REQUESTED", "APPROVED",
        "PARTIALLY_APPROVED", "DENIED", "REVERSED",
    )
    assert isinstance(data["evidence_item_count"], int) and data["evidence_item_count"] >= 0
    assert isinstance(data["evidence_request_count"], int)
    assert isinstance(data["refund_cents"], int) and data["refund_cents"] >= 0
    assert is_iso8601_timestamp(data["filed_at"])


# ─── Domain invariants ────────────────────────────────

def assert_money_invariants(order: dict) -> None:
    """The PRD's money waterfall, restated as invariants over one order row."""
    active_freight = (
        order["actual_freight_cents"] if order["settlement_basis"] == "FINAL"
        else order["estimated_freight_cents"]
    )
    expected_pre_fee = (
        order["hammer_price_cents"] + order["buyer_premium_cents"] + active_freight
    )
    assert order["pre_fee_total_cents"] == expected_pre_fee, (
        f"pre_fee_total_cents should be hammer + premium + freight = {expected_pre_fee}, "
        f"got {order['pre_fee_total_cents']}"
    )
    expected_total = (
        order["pre_fee_total_cents"] + order["late_fee_cents"] - order["claim_credit_cents"]
    )
    assert order["total_due_cents"] == expected_total, (
        f"total_due_cents should be {expected_total}, got {order['total_due_cents']}"
    )
    expected_balance = max(0, order["total_due_cents"] - order["amount_paid_cents"])
    assert order["balance_due_cents"] == expected_balance, (
        f"balance_due_cents should be {expected_balance} (clamped at zero), "
        f"got {order['balance_due_cents']}"
    )
    assert order["balance_due_cents"] >= 0, "balance_due_cents is clamped at zero"


def assert_lot_aggregates_match_lines(lot: dict, active_lines: list) -> None:
    """declared_unit_count / declared_retail_value_cents / manifest_line_count are
    recomputed over the lot's ACTIVE manifest lines only."""
    expected_units = sum(line["unit_count"] for line in active_lines)
    expected_retail = sum(
        line["unit_count"] * line["unit_retail_cents"] for line in active_lines
    )
    assert lot["declared_unit_count"] == expected_units, (
        f"declared_unit_count should be {expected_units}, got {lot['declared_unit_count']}"
    )
    assert lot["declared_retail_value_cents"] == expected_retail, (
        f"declared_retail_value_cents should be {expected_retail}, "
        f"got {lot['declared_retail_value_cents']}"
    )
    assert lot["manifest_line_count"] == len(active_lines), (
        f"manifest_line_count should be {len(active_lines)}, got {lot['manifest_line_count']}"
    )


def assert_recovery_rate_precision(rate) -> None:
    """Recovery rates are reported to four decimal places."""
    assert isinstance(rate, (int, float)), f"recovery rate must be numeric, got {rate!r}"
    assert round(float(rate), 4) == float(rate), (
        f"recovery rate {rate} carries more than four decimal places"
    )


def assert_accuracy_score_precision(score) -> None:
    """Manifest accuracy figures are reported to three decimal places."""
    assert isinstance(score, (int, float)), f"accuracy score must be numeric, got {score!r}"
    assert round(float(score), 3) == float(score), (
        f"accuracy score {score} carries more than three decimal places"
    )
    assert 0.0 <= float(score) <= 1.0, f"accuracy score {score} must be within 0.000-1.000"


def assert_analytics_envelope(data: dict) -> None:
    """The recovery analytics response reports six figures plus a groups array."""
    for field in ("seller_id", "group_by", "gross_hammer_cents",
                  "listed_retail_value_cents", "gross_recovery_rate",
                  "net_proceeds_cents", "sold_retail_value_cents", "net_recovery_rate"):
        assert field in data, f"recovery analytics must report {field}"
    assert data["group_by"] in ("NONE", "CATEGORY", "CHANNEL")
    assert isinstance(data["groups"], list), "groups must be an array"
    assert_recovery_rate_precision(data["gross_recovery_rate"])
    assert_recovery_rate_precision(data["net_recovery_rate"])
