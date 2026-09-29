"""Payload factories — one per write operation, input fields only."""
from .constants import TEST_DEFAULTS


def seller_payload(**overrides) -> dict:
    payload = {
        "legal_name": TEST_DEFAULTS["SELLER_LEGAL_NAME"],
        "storage_cubic_feet_entitlement": TEST_DEFAULTS["STORAGE_ENTITLEMENT"],
        "unit_cost_cap_cents": TEST_DEFAULTS["UNIT_COST_CAP_CENTS"],
    }
    payload.update(overrides)
    return payload


def fulfillment_center_payload(**overrides) -> dict:
    payload = {
        "fc_code": TEST_DEFAULTS["FC_CODE"],
        "region_code": TEST_DEFAULTS["REGION_CODE"],
        "prep_profile": TEST_DEFAULTS["PREP_PROFILE"],
        "case_pack_min_units": TEST_DEFAULTS["CASE_PACK_MIN_UNITS"],
        "receiving_capacity_units_per_window": TEST_DEFAULTS["RECEIVING_CAPACITY"],
        "monthly_storage_rate_cents_per_cubic_foot": TEST_DEFAULTS["MONTHLY_STORAGE_RATE"],
        "ltsf_rate_cents_per_cubic_foot": TEST_DEFAULTS["LTSF_RATE"],
    }
    payload.update(overrides)
    return payload


def sku_listing_payload(seller_account_id: str, **overrides) -> dict:
    payload = {
        "seller_account_id": seller_account_id,
        "sku": TEST_DEFAULTS["SKU"],
        "unit_cubic_feet": TEST_DEFAULTS["UNIT_CUBIC_FEET"],
        "unit_cost_cents": TEST_DEFAULTS["UNIT_COST_CENTS"],
    }
    payload.update(overrides)
    return payload


def restock_quota_payload(**overrides) -> dict:
    payload = {
        "period_start": TEST_DEFAULTS["QUOTA_PERIOD_START"],
        "period_end": TEST_DEFAULTS["QUOTA_PERIOD_END"],
        "base_capacity_units": TEST_DEFAULTS["BASE_CAPACITY_UNITS"],
        "sell_through_rate": TEST_DEFAULTS["SELL_THROUGH_RATE"],
        "excess_units_ratio": TEST_DEFAULTS["EXCESS_UNITS_RATIO"],
        "stranded_ratio": TEST_DEFAULTS["STRANDED_RATIO"],
        "in_stock_rate": TEST_DEFAULTS["IN_STOCK_RATE"],
    }
    payload.update(overrides)
    return payload


def inbound_plan_payload(
    seller_account_id: str,
    destination_fc_id: str,
    expected_seller_account_version: int,
    appointment_window_start: str = "2026-08-10T00:00:00Z",
    appointment_window_end: str = "2026-08-11T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "seller_account_id": seller_account_id,
        "destination_fc_id": destination_fc_id,
        "appointment_window_start": appointment_window_start,
        "appointment_window_end": appointment_window_end,
        "expected_seller_account_version": expected_seller_account_version,
    }
    payload.update(overrides)
    return payload


def line_item_payload(sku_listing_id: str, units: int, **overrides) -> dict:
    payload = {
        "sku_listing_id": sku_listing_id,
        "units": units,
        "case_pack_units": 10,
        "polybagged": True,
        "label_type": "FNSKU",
    }
    payload.update(overrides)
    return payload


def received_line(shipment_line_item_id: str, received_units: int,
                  unfulfillable_units: int = 0) -> dict:
    return {
        "shipment_line_item_id": shipment_line_item_id,
        "received_units": received_units,
        "unfulfillable_units": unfulfillable_units,
    }


def receipt_payload(received_lines: list, **overrides) -> dict:
    payload = {"received_lines": received_lines}
    payload.update(overrides)
    return payload


def unfulfillable_classification_payload(units: int,
                                         disposition_reason: str = "CUSTOMER_DAMAGE",
                                         **overrides) -> dict:
    payload = {"units": units, "disposition_reason": disposition_reason}
    payload.update(overrides)
    return payload


def removal_order_payload(
    inventory_lot_id: str,
    expected_inventory_lot_version: int,
    requested_units: int,
    removal_method: str = "DISPOSAL",
    unit_pool: str = "FULFILLABLE",
    removal_window_start: str = "2026-09-01T00:00:00Z",
    removal_window_end: str = "2026-09-02T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "inventory_lot_id": inventory_lot_id,
        "removal_method": removal_method,
        "unit_pool": unit_pool,
        "requested_units": requested_units,
        "removal_window_start": removal_window_start,
        "removal_window_end": removal_window_end,
        "expected_inventory_lot_version": expected_inventory_lot_version,
    }
    payload.update(overrides)
    return payload


def reimbursement_claim_payload(
    inventory_lot_id: str,
    claim_type: str,
    claimed_units: int,
    evidence_document_count: int,
    evidence_reference: str = "CASE-1",
    **overrides,
) -> dict:
    payload = {
        "inventory_lot_id": inventory_lot_id,
        "claim_type": claim_type,
        "claimed_units": claimed_units,
        "evidence_document_count": evidence_document_count,
        "evidence_reference": evidence_reference,
    }
    payload.update(overrides)
    return payload


def velocity_forecast_payload(
    forecast_variant: str = "TRAILING_30",
    trailing_30_units_sold: int = 600,
    prior_year_same_period_units_sold: int = 0,
    seasonal_index: float = 1.00,
    coverage_target_days: int = 30,
    lead_time_days: int = 30,
    **overrides,
) -> dict:
    payload = {
        "forecast_variant": forecast_variant,
        "trailing_30_units_sold": trailing_30_units_sold,
        "prior_year_same_period_units_sold": prior_year_same_period_units_sold,
        "seasonal_index": seasonal_index,
        "coverage_target_days": coverage_target_days,
        "lead_time_days": lead_time_days,
    }
    payload.update(overrides)
    return payload


def multi_channel_order_payload(
    sku_listing_id: str,
    units: int,
    billable_weight_lb: float,
    destination_zone: str,
    fulfillment_channel: str,
    self_fulfilled_cost_cents: int,
    **overrides,
) -> dict:
    payload = {
        "sku_listing_id": sku_listing_id,
        "units": units,
        "billable_weight_lb": billable_weight_lb,
        "destination_zone": destination_zone,
        "fulfillment_channel": fulfillment_channel,
        "self_fulfilled_cost_cents": self_fulfilled_cost_cents,
    }
    payload.update(overrides)
    return payload
