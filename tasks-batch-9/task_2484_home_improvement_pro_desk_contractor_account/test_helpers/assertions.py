"""Resource assertions and domain invariant checkers."""

from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    CreditLineStatus,
    CreditStatus,
    DeliveryAppointmentStatus,
    DeliveryMode,
    DeliveryTruckStatus,
    FulfillmentStatus,
    JobQuoteStatus,
    JobsiteAccessType,
    PaymentMethod,
    PriceSource,
    ProAccountStatus,
    RebatePayoutStatus,
    ReservationStatus,
    ReturnReasonCode,
    ReturnRequestStatus,
    ReturnValuationMode,
    TaxExemptCertificateStatus,
    TierCode,
    TierReviewMode,
    WillCallStagingStatus,
)


def _values(enum_cls) -> list:
    return [member.value for member in enum_cls]


def assert_common_fields(data: dict) -> None:
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1, got {data['version']}"


# --------------------------------------------------------------------------- #
# Per-resource assertions                                                      #
# --------------------------------------------------------------------------- #


def assert_store(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["store_code"], str) and data["store_code"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data["distance_rank"], int)
    assert isinstance(data["will_call_bay_slots"], int)
    assert isinstance(data["lift_gate_available"], bool)
    assert isinstance(data["tax_rate_pct"], (int, float))
    assert isinstance(data["max_stage_hours"], int)


def assert_store_stock(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["store_id"], str)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["on_hand_units"], int)
    assert isinstance(data["reserved_units"], int)
    assert isinstance(data["available_units"], int)
    assert isinstance(data["list_unit_price_cents"], int)
    assert_store_stock_invariants(data)


def assert_store_stock_invariants(data: dict) -> None:
    """on_hand minus reserved is what remains bookable, and never goes negative."""
    assert data["reserved_units"] >= 0, "reserved_units must never go negative"
    assert (
        data["available_units"] == data["on_hand_units"] - data["reserved_units"]
    ), (
        f"available_units {data['available_units']} must equal on_hand_units "
        f"{data['on_hand_units']} minus reserved_units {data['reserved_units']}"
    )
    assert data["available_units"] >= 0, "available_units must never go negative"


def assert_delivery_truck(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["store_id"], str)
    assert isinstance(data["truck_code"], str) and data["truck_code"]
    assert isinstance(data["lift_gate_equipped"], bool)
    assert isinstance(data["turnaround_buffer_minutes"], int)
    assert isinstance(data["access_types_supported"], list)
    for access_type in data["access_types_supported"]:
        assert access_type in _values(JobsiteAccessType)
    assert data["status"] in _values(DeliveryTruckStatus)


def assert_pro_account(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["business_name"], str) and data["business_name"]
    assert isinstance(data["home_store_id"], str)
    assert isinstance(data["po_required"], bool)
    assert isinstance(data["job_name_required"], bool)
    assert data["tier_review_mode"] in _values(TierReviewMode)
    assert isinstance(data["baseline_volume_cents"], int)
    assert isinstance(data["trailing_volume_cents"], int)
    assert data["tier_code"] in _values(TierCode)
    assert isinstance(data["tier_discount_pct"], (int, float))
    assert isinstance(data["tax_exempt_state_codes"], list)
    assert data["status"] in _values(ProAccountStatus)


def assert_credit_line(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["pro_account_id"], str)
    assert isinstance(data["limit_cents"], int) and data["limit_cents"] > 0
    assert isinstance(data["terms_days"], int)
    assert isinstance(data["exposure_cents"], int)
    assert isinstance(data["available_cents"], int)
    assert data["status"] in _values(CreditLineStatus)
    assert_credit_line_invariants(data)


def assert_credit_line_invariants(data: dict) -> None:
    """Headroom is the limit less current exposure."""
    assert (
        data["available_cents"] == data["limit_cents"] - data["exposure_cents"]
    ), (
        f"available_cents {data['available_cents']} must equal limit_cents "
        f"{data['limit_cents']} minus exposure_cents {data['exposure_cents']}"
    )


def assert_tax_exempt_certificate(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["pro_account_id"], str)
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data["certificate_number"], str) and data["certificate_number"]
    assert isinstance(data["expires_on"], str) and data["expires_on"]
    assert data["status"] in _values(TaxExemptCertificateStatus)


def assert_job_quote(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["pro_account_id"], str)
    assert isinstance(data["originating_store_id"], str)
    assert isinstance(data["job_name"], str) and data["job_name"]
    assert isinstance(data["requested_term_days"], int)
    assert data["status"] in _values(JobQuoteStatus)
    assert isinstance(data["round_count"], int) and data["round_count"] >= 0
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_quote_line(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["job_quote_id"], str)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["qty_units"], int) and data["qty_units"] > 0


def assert_pro_order(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["pro_account_id"], str)
    assert isinstance(data["fulfillment_store_id"], str)
    assert data["payment_method"] in _values(PaymentMethod)
    assert data["delivery_mode"] in _values(DeliveryMode)
    assert isinstance(data["lift_gate_required"], bool)
    assert isinstance(data["job_lot_required"], bool)
    assert isinstance(data["resale_purchase"], bool)
    assert data["fulfillment_status"] in _values(FulfillmentStatus)
    assert data["credit_status"] in _values(CreditStatus)
    assert isinstance(data["tax_exempt_applied"], bool)


def assert_priced_order_totals(data: dict) -> None:
    """A priced order's money legs add up to its total."""
    expected_total = (
        data["subtotal_cents"]
        + data["freight_surcharge_cents"]
        + data["lift_gate_fee_cents"]
        + data["tax_cents"]
    )
    assert data["total_cents"] == expected_total, (
        f"total_cents {data['total_cents']} must equal subtotal "
        f"{data['subtotal_cents']} + freight {data['freight_surcharge_cents']} + "
        f"lift gate {data['lift_gate_fee_cents']} + tax {data['tax_cents']} "
        f"= {expected_total}"
    )
    assert (
        data["discount_cents"] == data["list_subtotal_cents"] - data["subtotal_cents"]
    ), "discount_cents must be the gap between the list subtotal and the charged subtotal"


def assert_order_line(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["pro_order_id"], str)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["qty_units"], int) and data["qty_units"] > 0
    if data.get("price_source") is not None:
        assert data["price_source"] in _values(PriceSource)
    assert isinstance(data["fulfilled_units"], int)
    assert isinstance(data["returned_units"], int)
    assert data["returned_units"] <= data["qty_units"]


def assert_reservation(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["pro_order_id"], str)
    assert isinstance(data["order_line_id"], str)
    assert isinstance(data["store_id"], str)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["qty_units"], int) and data["qty_units"] > 0
    assert data["status"] in _values(ReservationStatus)


def assert_will_call_staging(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["pro_order_id"], str)
    assert isinstance(data["store_id"], str)
    assert is_iso8601_timestamp(data["stage_start"])
    assert isinstance(data["stage_hours"], int) and data["stage_hours"] > 0
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in _values(WillCallStagingStatus)


def assert_delivery_appointment(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["pro_order_id"], str)
    assert isinstance(data["delivery_truck_id"], str)
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["jobsite_access_type"] in _values(JobsiteAccessType)
    assert data["status"] in _values(DeliveryAppointmentStatus)


def assert_rebate_accrual(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["pro_account_id"], str)
    assert isinstance(data["period_start"], str) and data["period_start"]
    assert isinstance(data["period_end"], str) and data["period_end"]
    assert isinstance(data["accrued_cents"], int)
    assert isinstance(data["clawed_back_cents"], int)
    assert isinstance(data["payable_cents"], int)
    assert data["payout_status"] in _values(RebatePayoutStatus)
    assert_rebate_accrual_invariants(data)


def assert_rebate_accrual_invariants(data: dict) -> None:
    """What is still payable is what was accrued less what was clawed back, floored at zero."""
    expected = max(0, data["accrued_cents"] - data["clawed_back_cents"])
    assert data["payable_cents"] == expected, (
        f"payable_cents {data['payable_cents']} must equal accrued "
        f"{data['accrued_cents']} minus clawed back {data['clawed_back_cents']} "
        f"floored at zero = {expected}"
    )
    assert data["payable_cents"] >= 0


def assert_return_request(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["pro_order_id"], str)
    assert data["reason_code"] in _values(ReturnReasonCode)
    assert isinstance(data["lines"], list) and len(data["lines"]) > 0
    assert data["status"] in _values(ReturnRequestStatus)
    if data.get("valuation_mode") is not None:
        assert data["valuation_mode"] in _values(ReturnValuationMode)


def assert_refund_legs_sum(data: dict) -> None:
    """The credited amount is goods net of the restocking fee plus the tax refund."""
    expected = (
        data["gross_refund_cents"]
        - data["restocking_fee_cents"]
        + data["tax_refund_cents"]
    )
    assert data["refund_total_cents"] == expected, (
        f"refund_total_cents {data['refund_total_cents']} must equal gross "
        f"{data['gross_refund_cents']} minus restocking fee "
        f"{data['restocking_fee_cents']} plus tax refund "
        f"{data['tax_refund_cents']} = {expected}"
    )


# --------------------------------------------------------------------------- #
# Cross-resource helpers                                                       #
# --------------------------------------------------------------------------- #


def assert_order_dimensions(
    order: dict,
    fulfillment_status: Optional[str] = None,
    credit_status: Optional[str] = None,
) -> None:
    """Assert the physical and commercial dimensions of an order independently."""
    if fulfillment_status is not None:
        assert order["fulfillment_status"] == fulfillment_status, (
            f"expected fulfillment_status {fulfillment_status}, got "
            f"{order['fulfillment_status']}"
        )
    if credit_status is not None:
        assert order["credit_status"] == credit_status, (
            f"expected credit_status {credit_status}, got {order['credit_status']}"
        )


def assert_pagination_meta(
    meta: dict, limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"expected has_more {has_more}, got {meta['has_more']}"
    )
