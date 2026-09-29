"""Payload factories — one per entity, input fields only."""

import hashlib
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


def create_vendor_payload(**overrides) -> Dict[str, Any]:
    """COMMISSION vendor by default; pass cost_model=WHOLESALE plus
    wholesale_discount_bps for the other cost model."""
    payload: Dict[str, Any] = {
        "vendor_code": TEST_DEFAULTS["VENDOR_CODE"],
        "legal_name": TEST_DEFAULTS["LEGAL_NAME"],
        "cost_model": "COMMISSION",
        "commission_rate_bps": TEST_DEFAULTS["COMMISSION_RATE_BPS"],
        "inventory_refresh_cadence_minutes": TEST_DEFAULTS["CADENCE_MINUTES"],
        "safety_buffer_units": TEST_DEFAULTS["SAFETY_BUFFER_UNITS"],
        "oversell_grace_units": TEST_DEFAULTS["OVERSELL_GRACE_UNITS"],
        "default_lead_time_days": TEST_DEFAULTS["DEFAULT_LEAD_TIME_DAYS"],
        "ack_sla_hours": TEST_DEFAULTS["ACK_SLA_HOURS"],
        "ship_sla_grace_hours": TEST_DEFAULTS["SHIP_SLA_GRACE_HOURS"],
    }
    payload.update(overrides)
    if payload.get("cost_model") == "WHOLESALE":
        payload.pop("commission_rate_bps", None)
        payload.setdefault(
            "wholesale_discount_bps", TEST_DEFAULTS["WHOLESALE_DISCOUNT_BPS"]
        )
    # Explicit None overrides mean "omit the field".
    return {k: v for k, v in payload.items() if v is not None}


def create_wholesale_vendor_payload(**overrides) -> Dict[str, Any]:
    """WHOLESALE vendor payload."""
    overrides.setdefault("cost_model", "WHOLESALE")
    return create_vendor_payload(**overrides)


def create_integration_test_payload(
    message_type: str = "CATALOG", **overrides
) -> Dict[str, Any]:
    # The digest is the hex digest of the sample message: 8..64 hexadecimal
    # characters and nothing else.
    payload: Dict[str, Any] = {
        "message_type": message_type,
        "sample_payload_digest": hashlib.sha256(message_type.encode()).hexdigest(),
    }
    payload.update(overrides)
    return payload


def evaluate_integration_test_payload(
    outcome: str = "PASS", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome, "reported_error_count": 0}
    payload.update(overrides)
    return payload


def create_serviceability_rule_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "zone_code": TEST_DEFAULTS["ZONE_CODE"],
        "ship_method": TEST_DEFAULTS["SHIP_METHOD"],
        "transit_days": TEST_DEFAULTS["TRANSIT_DAYS"],
        "cutoff_hour_utc": TEST_DEFAULTS["CUTOFF_HOUR_UTC"],
        "surcharge_cents": TEST_DEFAULTS["SURCHARGE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_blackout_payload(
    start_date: str = "2026-09-01", end_date: str = "2026-09-05", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "start_date": start_date,
        "end_date": end_date,
        "reason": "HOLIDAY",
    }
    payload.update(overrides)
    return payload


def create_item_payload(vendor_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "vendor_id": vendor_id,
        "sku": TEST_DEFAULTS["SKU"],
        "unit_retail_cents": TEST_DEFAULTS["UNIT_RETAIL_CENTS"],
        "ship_method": TEST_DEFAULTS["SHIP_METHOD"],
        "lead_time_days": TEST_DEFAULTS["LEAD_TIME_DAYS"],
        "reverse_freight_owner": "RETAILER",
        "restock_policy": "VENDOR_RESTOCK",
        "defect_window_days": TEST_DEFAULTS["DEFECT_WINDOW_DAYS"],
    }
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not None}


def create_inventory_snapshot_payload(
    expected_item_version: int,
    on_hand_units: int = TEST_DEFAULTS["ON_HAND_UNITS"],
    effective_from: str = "2026-08-03T09:00:00Z",
    feed_sequence: int = 1,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "on_hand_units": on_hand_units,
        "effective_from": effective_from,
        "feed_sequence": feed_sequence,
        "expected_item_version": expected_item_version,
    }
    payload.update(overrides)
    return payload


def create_order_payload(
    order_ref: str,
    lines: List[Dict[str, Any]],
    customer_zone_code: str = TEST_DEFAULTS["ZONE_CODE"],
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "order_ref": order_ref,
        "customer_zone_code": customer_zone_code,
        "lines": lines,
    }
    payload.update(overrides)
    return payload


def order_line_input(item_id: str, quantity: int = 1) -> Dict[str, Any]:
    return {"item_id": item_id, "quantity": quantity}


def acknowledge_payload(ack_disposition: str = "ACCEPTED") -> Dict[str, Any]:
    return {"ack_disposition": ack_disposition}


def ship_confirm_payload(
    shipped_units: int,
    carrier: str = "UPS",
    tracking_number: str = TEST_DEFAULTS["TRACKING_NUMBER"],
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "carrier": carrier,
        "tracking_number": tracking_number,
        "shipped_units": shipped_units,
    }
    payload.update(overrides)
    return payload


def create_return_payload(
    line_id: str, quantity_returned: int = 1, reason_code: str = "DEFECTIVE", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "line_id": line_id,
        "reason_code": reason_code,
        "quantity_returned": quantity_returned,
    }
    payload.update(overrides)
    return payload


def reject_return_payload(rejection_reason: str = "POLICY") -> Dict[str, Any]:
    return {"rejection_reason": rejection_reason}


def receive_return_payload(restocked_units: Optional[int] = None) -> Dict[str, Any]:
    if restocked_units is None:
        return {}
    return {"restocked_units": restocked_units}


def create_scorecard_payload(
    period_start: str = "2026-07-01", period_end: str = "2026-07-31", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not None}


def seeded_scorecard_payload(
    avg_ship_hours: float,
    on_time_bps: int,
    cancellation_bps: int,
    defect_bps: int,
    period_start: str = "2026-07-01",
    period_end: str = "2026-07-31",
    metric_variant: str = "EVENT_EQUAL",
) -> Dict[str, Any]:
    """Scorecard computed purely from seeded prior history."""
    return {
        "period_start": period_start,
        "period_end": period_end,
        "metric_variant": metric_variant,
        "seeded_prior_avg_ship_hours": avg_ship_hours,
        "seeded_prior_on_time_ship_rate_bps": on_time_bps,
        "seeded_prior_cancellation_rate_bps": cancellation_bps,
        "seeded_prior_defect_rate_bps": defect_bps,
    }
