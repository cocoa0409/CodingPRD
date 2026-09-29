"""Payload factories — one per resource, carrying only client-supplied fields."""

from typing import Any, Dict, List

from .constants import LIST_PRICE_CENTS, SKU_SHINGLE_BUNDLE, TEST_DEFAULTS


def create_store_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "store_code": TEST_DEFAULTS["STORE_CODE"],
        "region_code": TEST_DEFAULTS["REGION_CODE"],
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "distance_rank": TEST_DEFAULTS["DISTANCE_RANK"],
        "will_call_bay_slots": TEST_DEFAULTS["WILL_CALL_BAY_SLOTS"],
        "lift_gate_available": TEST_DEFAULTS["LIFT_GATE_AVAILABLE"],
        "tax_rate_pct": TEST_DEFAULTS["TAX_RATE_PCT"],
        "max_stage_hours": TEST_DEFAULTS["MAX_STAGE_HOURS"],
    }
    payload.update(overrides)
    return payload


def create_store_stock_payload(store_id: str, sku: str = SKU_SHINGLE_BUNDLE, **overrides) -> Dict[str, Any]:
    payload = {
        "store_id": store_id,
        "sku": sku,
        "on_hand_units": TEST_DEFAULTS["ON_HAND_UNITS"],
        "list_unit_price_cents": LIST_PRICE_CENTS.get(sku, 1_000),
    }
    payload.update(overrides)
    return payload


def create_delivery_truck_payload(store_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "store_id": store_id,
        "truck_code": TEST_DEFAULTS["TRUCK_CODE"],
        "lift_gate_equipped": True,
        "access_types_supported": ["CURBSIDE", "DRIVEWAY"],
        "turnaround_buffer_minutes": TEST_DEFAULTS["TURNAROUND_BUFFER_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_pro_account_payload(home_store_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "business_name": TEST_DEFAULTS["BUSINESS_NAME"],
        "home_store_id": home_store_id,
        "po_required": False,
        "job_name_required": False,
        "tier_review_mode": "PINNED_AT_REVIEW",
        "baseline_volume_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_credit_line_payload(pro_account_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "pro_account_id": pro_account_id,
        "limit_cents": 500_000,
        "terms_days": 30,
    }
    payload.update(overrides)
    return payload


def create_tax_exempt_certificate_payload(
    pro_account_id: str, expected_pro_account_version: int, **overrides
) -> Dict[str, Any]:
    payload = {
        "pro_account_id": pro_account_id,
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "certificate_number": "IL-RESALE-77120",
        "expires_on": "2027-12-31",
        "expected_pro_account_version": expected_pro_account_version,
    }
    payload.update(overrides)
    return payload


def create_job_quote_payload(
    pro_account_id: str, originating_store_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "pro_account_id": pro_account_id,
        "originating_store_id": originating_store_id,
        "job_name": "MAPLE-ST-REROOF",
        "requested_term_days": 30,
    }
    payload.update(overrides)
    return payload


def create_quote_line_payload(sku: str = SKU_SHINGLE_BUNDLE, qty_units: int = 8) -> Dict[str, Any]:
    return {"sku": sku, "qty_units": qty_units}


def create_pro_order_payload(
    pro_account_id: str, fulfillment_store_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "pro_account_id": pro_account_id,
        "fulfillment_store_id": fulfillment_store_id,
        "payment_method": "CARD",
        "delivery_mode": "WILL_CALL",
        "lift_gate_required": False,
        "job_lot_required": False,
        "resale_purchase": False,
    }
    payload.update(overrides)
    return payload


def create_order_line_payload(sku: str = SKU_SHINGLE_BUNDLE, qty_units: int = 10) -> Dict[str, Any]:
    return {"sku": sku, "qty_units": qty_units}


def create_will_call_staging_payload(
    pro_order_id: str, store_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "pro_order_id": pro_order_id,
        "store_id": store_id,
        "stage_start": "2026-08-02T08:00:00Z",
        "stage_hours": 6,
    }
    payload.update(overrides)
    return payload


def create_delivery_appointment_payload(
    pro_order_id: str, delivery_truck_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "pro_order_id": pro_order_id,
        "delivery_truck_id": delivery_truck_id,
        "window_start": "2026-08-05T09:00:00Z",
        "window_end": "2026-08-05T11:00:00Z",
        "jobsite_access_type": "CURBSIDE",
    }
    payload.update(overrides)
    return payload


def create_return_request_payload(
    pro_order_id: str, lines: List[Dict[str, Any]], **overrides
) -> Dict[str, Any]:
    payload = {
        "pro_order_id": pro_order_id,
        "reason_code": "OVER_ORDERED",
        "lines": lines,
    }
    payload.update(overrides)
    return payload


def counter_offer_line_price(quote_line_id: str, negotiated_unit_price_cents: int) -> Dict[str, Any]:
    return {
        "quote_line_id": quote_line_id,
        "negotiated_unit_price_cents": negotiated_unit_price_cents,
    }


def return_line(order_line_id: str, qty_units: int) -> Dict[str, Any]:
    return {"order_line_id": order_line_id, "qty_units": qty_units}
