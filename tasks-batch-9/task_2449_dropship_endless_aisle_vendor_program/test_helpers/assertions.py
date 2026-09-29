"""Entity assertions and domain invariant checkers."""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import THRESHOLDS


# ─── Shared shape helpers ─────────────────────────────


def assert_common_fields(data: Dict[str, Any]) -> None:
    """id, created_at, updated_at and version are present and well formed."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version must start at 1"


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """An append-only row carries id and created_at and nothing else common."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601: {data.get('created_at')!r}"
    assert "updated_at" not in data, "append-only rows must not carry updated_at"
    assert "version" not in data, "append-only rows must not carry version"


def _assert_enum(data: Dict[str, Any], field: str, allowed: List[str]) -> None:
    assert data.get(field) in allowed, (
        f"{field} must be one of {allowed}, got {data.get(field)!r}"
    )


def _assert_optional_enum(
    data: Dict[str, Any], field: str, allowed: List[str]
) -> None:
    value = data.get(field)
    assert value is None or value in allowed, (
        f"{field} must be null or one of {allowed}, got {value!r}"
    )


# ─── Per-entity assertions ────────────────────────────


def assert_vendor(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["vendor_code"], str) and 1 <= len(data["vendor_code"]) <= 32
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 200
    _assert_enum(data, "cost_model", ["COMMISSION", "WHOLESALE"])
    if data["cost_model"] == "COMMISSION":
        assert isinstance(data["commission_rate_bps"], int)
        assert 0 <= data["commission_rate_bps"] <= 5000
        assert data.get("wholesale_discount_bps") is None, (
            "a COMMISSION vendor must not carry wholesale_discount_bps"
        )
    else:
        assert isinstance(data["wholesale_discount_bps"], int)
        assert 0 <= data["wholesale_discount_bps"] <= 5000
        assert data.get("commission_rate_bps") is None, (
            "a WHOLESALE vendor must not carry commission_rate_bps"
        )
    assert 1 <= data["inventory_refresh_cadence_minutes"] <= 1440
    assert data["safety_buffer_units"] >= 0
    assert data["oversell_grace_units"] >= 0
    assert 0 <= data["default_lead_time_days"] <= 60
    assert 1 <= data["ack_sla_hours"] <= 168
    assert 0 <= data["ship_sla_grace_hours"] <= 168
    _assert_enum(
        data,
        "onboarding_status",
        ["DRAFT", "INTEGRATION_TESTING", "CERTIFIED", "ACTIVE", "SUSPENDED"],
    )
    assert data["integration_round"] >= 0
    _assert_optional_enum(
        data, "suspension_reason", ["SCORECARD_PROBATION", "MANUAL_OPS"]
    )
    _assert_enum(
        data,
        "performance_tier",
        ["UNRATED", "PLATINUM", "GOLD", "SILVER", "WATCH", "PROBATION"],
    )
    assert 0 <= data["promise_padding_days"] <= 5
    assert isinstance(data["settlement_balance_cents"], int)
    assert isinstance(data["chargeback_balance_cents"], int)


def assert_integration_test(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["vendor_id"])
    _assert_enum(
        data, "message_type", ["CATALOG", "INVENTORY", "ORDER", "SHIP_CONFIRM"]
    )
    assert data["round_number"] >= 1
    assert 8 <= len(data["sample_payload_digest"]) <= 64
    _assert_enum(data, "status", ["PENDING", "PASSED", "FAILED"])
    if data["status"] == "PENDING":
        assert data.get("evaluated_at") is None
        assert data.get("evaluated_by_user_id") is None
    else:
        assert is_iso8601_timestamp(data["evaluated_at"])
        assert data["evaluated_by_user_id"]


def assert_dropship_item(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["vendor_id"])
    assert isinstance(data["sku"], str) and 1 <= len(data["sku"]) <= 40
    assert 0 <= data["lead_time_days"] <= 60
    _assert_enum(data, "ship_method", ["GROUND", "TWO_DAY", "FREIGHT_LTL"])
    assert data["unit_retail_cents"] >= 1
    _assert_optional_enum(data, "reverse_freight_owner", ["VENDOR", "RETAILER"])
    _assert_optional_enum(
        data, "restock_policy", ["VENDOR_RESTOCK", "RETAILER_RESTOCK", "DESTROY"]
    )
    assert 1 <= data["defect_window_days"] <= 365
    _assert_enum(data, "status", ["DRAFT", "ACTIVE", "SUPPRESSED"])
    _assert_optional_enum(
        data,
        "suppression_reason",
        ["MANUAL", "VENDOR_SUSPENDED", "ZERO_AVAILABILITY"],
    )
    assert isinstance(data["inventory_is_stale"], bool)
    assert data["effective_on_hand_units"] >= 0
    assert data["reserved_units"] >= 0
    assert data["available_units"] >= 0
    if data["status"] != "ACTIVE":
        assert data["available_units"] == 0, (
            "an offer that is not ACTIVE must expose available_units 0"
        )
    assert_item_conservation(data)


def assert_serviceability_rule(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["vendor_id"])
    assert isinstance(data["zone_code"], str) and 1 <= len(data["zone_code"]) <= 16
    _assert_enum(data, "ship_method", ["GROUND", "TWO_DAY", "FREIGHT_LTL"])
    assert 1 <= data["transit_days"] <= 30
    assert 0 <= data["cutoff_hour_utc"] <= 23
    assert data["surcharge_cents"] >= 0
    _assert_enum(data, "status", ["ACTIVE", "INACTIVE"])
    assert isinstance(data["inactivated_by_suspension"], bool)


def assert_vendor_blackout(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["vendor_id"])
    assert data["start_date"] <= data["end_date"], "start_date must not exceed end_date"
    assert 0 <= data["reopen_buffer_days"] <= 14
    _assert_enum(
        data, "reason", ["HOLIDAY", "PEAK_FREEZE", "CAPACITY", "SYSTEM_CUTOVER"]
    )
    _assert_enum(data, "status", ["ACTIVE", "CANCELLED"])


def assert_inventory_snapshot(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["item_id"])
    assert data["on_hand_units"] >= 0
    assert is_iso8601_timestamp(data["effective_from"])
    if data.get("effective_to") is not None:
        assert is_iso8601_timestamp(data["effective_to"])
        assert data["effective_to"] > data["effective_from"], (
            "effective_to must be strictly after effective_from"
        )
    _assert_optional_enum(data, "source", ["VENDOR_FEED", "MANUAL_ADJUST"])
    _assert_enum(data, "status", ["ACTIVE", "SUPERSEDED"])
    assert data["feed_sequence"] >= 1


def assert_dropship_order(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["order_ref"], str) and 1 <= len(data["order_ref"]) <= 40
    assert (
        isinstance(data["customer_zone_code"], str)
        and 1 <= len(data["customer_zone_code"]) <= 16
    )
    assert is_iso8601_timestamp(data["placed_at"])
    _assert_enum(
        data,
        "fulfillment_status",
        ["OPEN", "PARTIALLY_SHIPPED", "SHIPPED", "CANCELLED"],
    )
    _assert_enum(
        data,
        "financial_status",
        ["PENDING", "CAPTURED", "PARTIALLY_REFUNDED", "REFUNDED"],
    )
    _assert_enum(data, "promise_variant_in_effect", ["QUOTED", "RECOMPUTED"])
    assert isinstance(data["total_retail_cents"], int)
    assert isinstance(data["total_cost_cents"], int)
    assert data["margin_cents"] == data["total_retail_cents"] - data["total_cost_cents"]
    assert data["refunded_cents"] >= 0


def assert_dropship_order_line(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["item_id"])
    assert data["line_number"] >= 1
    assert data["quantity"] >= 1
    _assert_enum(
        data,
        "status",
        [
            "PENDING_TRANSMIT",
            "TRANSMITTED",
            "ACKNOWLEDGED",
            "BACKORDERED",
            "SHIPPED",
            "CANCELLED_BY_VENDOR",
        ],
    )
    assert isinstance(data["ack_sla_breached"], bool)
    assert isinstance(data["ship_sla_breached"], bool)
    assert data["transmit_attempt_count"] >= 0
    assert data["returned_units"] >= 0
    assert data["returned_units"] <= data["quantity"], (
        "returned_units can never exceed the line quantity"
    )
    if data["status"] == "PENDING_TRANSMIT":
        assert data["transmitted_at"] is None
        assert data["unit_cost_cents"] == 0, (
            "an untransmitted line carries no pinned unit cost"
        )
        assert data["surcharge_cents"] == 0


def assert_shipment_confirmation(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["line_id"])
    _assert_enum(data, "carrier", ["UPS", "FEDEX", "USPS", "LTL_CARRIER"])
    assert 4 <= len(data["tracking_number"]) <= 40
    assert data["shipped_units"] >= 1
    assert data["package_count"] >= 1
    assert isinstance(data["on_time"], bool)
    assert data["ship_hours"] >= 0


def assert_return_authorization(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["line_id"])
    _assert_enum(
        data,
        "reason_code",
        ["DEFECTIVE", "NOT_AS_DESCRIBED", "BUYER_REMORSE", "LATE_DELIVERY"],
    )
    assert data["quantity_returned"] >= 1
    _assert_enum(data, "status", ["REQUESTED", "AUTHORIZED", "RECEIVED", "REJECTED"])
    _assert_optional_enum(data, "routing_destination", ["VENDOR", "RETAILER_DC"])
    _assert_optional_enum(data, "reverse_freight_owner", ["VENDOR", "RETAILER"])
    _assert_optional_enum(
        data, "restock_disposition", ["VENDOR_RESTOCK", "RETAILER_RESTOCK", "DESTROY"]
    )
    _assert_optional_enum(
        data, "rejection_reason", ["OUTSIDE_DEFECT_WINDOW", "NOT_RECEIVED", "POLICY"]
    )
    assert data["restocked_units"] >= 0
    if data["status"] == "REQUESTED":
        assert data.get("refund_cents") is None, (
            "financials are derived at authorization, not at request time"
        )
        assert data.get("routing_destination") is None


def assert_vendor_scorecard(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["vendor_id"])
    assert data["period_start"] <= data["period_end"]
    _assert_enum(data, "metric_variant", ["EVENT_EQUAL", "UNIT_WEIGHTED"])
    _assert_enum(
        data, "tier", ["UNRATED", "PLATINUM", "GOLD", "SILVER", "WATCH", "PROBATION"]
    )
    _assert_enum(data, "status", ["DRAFT", "PUBLISHED"])
    assert 0 <= data["promise_padding_days"] <= 5
    for field in (
        "transmitted_line_count",
        "shipped_line_count",
        "cancelled_line_count",
        "defect_return_count",
        "transmitted_unit_count",
        "shipped_unit_count",
        "cancelled_unit_count",
        "defect_unit_count",
    ):
        assert data[field] >= 0, f"{field} must be non-negative"
    for field in (
        "on_time_ship_rate_bps",
        "cancellation_rate_bps",
        "defect_rate_bps",
    ):
        if data.get(field) is not None:
            assert 0 <= data[field] <= 10000, f"{field} must be within 0..10000"
    if data["status"] == "PUBLISHED":
        assert is_iso8601_timestamp(data["published_at"])
    else:
        assert data.get("published_at") is None


# ─── Domain invariant checkers ────────────────────────


def assert_item_conservation(item: Dict[str, Any]) -> None:
    """Physical-unit conservation on one offer."""
    expected = (
        item["lifetime_reserved_units"]
        - item["lifetime_released_units"]
        - item["lifetime_shipped_units"]
    )
    assert item["reserved_units"] == expected, (
        "reserved_units must equal lifetime_reserved_units minus "
        f"lifetime_released_units minus lifetime_shipped_units: "
        f"{item['reserved_units']} != {expected}"
    )


def assert_vendor_ledger_conservation(
    vendor: Dict[str, Any], shipped_lines: List[Dict[str, Any]]
) -> None:
    """Monetary conservation: the two vendor balances sum to the shipped-line total."""
    expected = sum(
        line["unit_cost_cents"] * line["quantity"] + line["surcharge_cents"]
        for line in shipped_lines
    )
    actual = vendor["settlement_balance_cents"] + vendor["chargeback_balance_cents"]
    assert actual == expected, (
        "settlement_balance_cents plus chargeback_balance_cents must equal the "
        f"shipped-line total: {actual} != {expected}"
    )


def assert_availability(
    item: Dict[str, Any],
    on_hand: int,
    safety_buffer: int,
    oversell_grace: int,
) -> None:
    """available_units follows the buffer/grace/reservation formula."""
    expected = max(0, on_hand - safety_buffer + oversell_grace - item["reserved_units"])
    assert item["available_units"] == expected, (
        f"available_units must be {expected}, got {item['available_units']}"
    )


def assert_tier_for_score(tier: str, composite_score: Optional[float]) -> None:
    """The published tier follows the composite-score cutoffs."""
    if composite_score is None:
        assert tier == "UNRATED", "a scorecard with no composite score is UNRATED"
        return
    if composite_score >= 95:
        expected = "PLATINUM"
    elif composite_score >= 90:
        expected = "GOLD"
    elif composite_score >= 80:
        expected = "SILVER"
    elif composite_score >= 70:
        expected = "WATCH"
    else:
        expected = "PROBATION"
    assert tier == expected, (
        f"composite score {composite_score} maps to tier {expected}, got {tier}"
    )


def assert_restock_fee_tier(refund_base_cents: int, restocking_fee_cents: int) -> None:
    """The restocking fee tier is keyed on the pre-fee refund base."""
    if refund_base_cents < 5000:
        rate = 0
    elif refund_base_cents < 20000:
        rate = 500
    else:
        rate = 1000
    expected = (refund_base_cents * rate + 5000) // 10000
    assert restocking_fee_cents == expected, (
        f"a base of {refund_base_cents} sits in the {rate} bps tier, so the fee "
        f"must be {expected}, got {restocking_fee_cents}"
    )


def assert_refund_waterfall(ra: Dict[str, Any]) -> None:
    """refund_cents is the base less the fee less the customer freight charge."""
    expected = (
        ra["refund_base_cents"]
        - ra["restocking_fee_cents"]
        - ra["customer_freight_charge_cents"]
    )
    assert ra["refund_cents"] == expected, (
        f"refund_cents must be {expected}, got {ra['refund_cents']}"
    )


def assert_reverse_freight_flat(charge_cents: int) -> None:
    assert charge_cents == THRESHOLDS["REVERSE_FREIGHT_FLAT_CENTS"], (
        f"the reverse-freight charge is flat at "
        f"{THRESHOLDS['REVERSE_FREIGHT_FLAT_CENTS']}, got {charge_cents}"
    )
