"""Resource serializers — field-by-field per SCAFFOLD §1.1."""
from datetime import datetime
from decimal import Decimal

import clock
from calc import lot_age_days

COMMON = ("id", "created_at", "updated_at", "version")
APPEND_ONLY = ("id", "created_at")

SELLER_FIELDS = (
    "legal_name", "storage_cubic_feet_entitlement", "unit_cost_cap_cents",
    "seller_status", "restock_reserved_units", "open_discrepancy_units",
    "suppressed_listing_count", "storage_utilization_ratio",
    "storage_fee_accrued_cents", "reimbursement_credit_cents",
    "mcf_fee_accrued_cents",
)

FC_FIELDS = (
    "fc_code", "region_code", "prep_profile", "case_pack_min_units",
    "receiving_capacity_units_per_window",
    "monthly_storage_rate_cents_per_cubic_foot", "ltsf_rate_cents_per_cubic_foot",
    "receiving_status", "committed_receiving_units",
)

LISTING_FIELDS = (
    "seller_account_id", "sku", "unit_cubic_feet", "unit_cost_cents",
    "listing_status", "suppression_reason", "inventory_health",
    "fulfillable_units", "unfulfillable_units", "missing_units",
    "aged_over_365_units", "recommended_replenishment_units", "lot_ever_created",
)

QUOTA_FIELDS = (
    "seller_account_id", "period_start", "period_end", "base_capacity_units",
    "sell_through_rate", "excess_units_ratio", "stranded_ratio", "in_stock_rate",
    "iprs_score", "base_capacity_tier", "capacity_tier_downgrade_steps",
    "capacity_tier", "restock_limit_units", "utilized_units", "status",
)

PLAN_FIELDS = (
    "seller_account_id", "destination_fc_id", "appointment_window_start",
    "appointment_window_end", "status", "declared_units",
    "provisional_allocated_units", "final_allocated_units", "allocated_units",
    "allocation_status", "prep_compliance_status", "received_units",
    "missing_units", "confirmed_at",
)

LINE_ITEM_FIELDS = (
    "shipment_plan_id", "sku_listing_id", "units", "case_pack_units",
    "polybagged", "label_type", "provisional_allocated_units",
    "final_allocated_units", "received_units", "shortfall_units",
)

LOT_FIELDS = (
    "sku_listing_id", "fulfillment_center_id", "first_received_at",
    "units_received_total", "fulfillable_units", "unfulfillable_units",
    "units_reserved_for_removal", "units_removed", "units_shipped_mcf",
    "missing_units", "lot_status", "reconciliation_status", "age_days",
    "aged_bucket", "ltsf_exposed", "storage_fee_accrued_cents",
    "discrepancy_opened_at", "unfulfillable_recorded_at",
    "last_removal_completed_at",
)

ASSESSMENT_FIELDS = (
    "inventory_lot_id", "billing_run_sequence", "assessed_at",
    "age_days_at_assessment", "aged_bucket", "billable_cubic_feet",
    "monthly_storage_fee_cents", "ltsf_surcharge_cents", "total_fee_cents",
)

REMOVAL_FIELDS = (
    "inventory_lot_id", "removal_method", "unit_pool", "requested_units",
    "removal_window_start", "removal_window_end", "status", "removal_fee_cents",
    "liquidation_recovery_cents", "net_settlement_cents", "completed_at",
)

CLAIM_FIELDS = (
    "inventory_lot_id", "claim_type", "claimed_units", "evidence_document_count",
    "evidence_reference", "status", "resubmission_count", "filing_deadline_at",
    "eligible_units", "approved_units", "reimbursement_amount_cents", "decided_at",
)

FORECAST_FIELDS = (
    "sku_listing_id", "forecast_variant", "trailing_30_units_sold",
    "prior_year_same_period_units_sold", "seasonal_index",
    "coverage_target_days", "lead_time_days", "daily_velocity", "target_units",
    "in_flight_units", "quota_headroom_units", "recommended_replenishment_units",
    "stranded_risk_flag",
)

MCF_ORDER_FIELDS = (
    "sku_listing_id", "units", "billable_weight_lb", "destination_zone",
    "fulfillment_channel", "self_fulfilled_cost_cents", "is_peak_period",
    "mcf_fee_cents", "fee_advantage_cents", "recommended_channel",
    "order_status", "consumed_lot_allocations",
)


def _value(value):
    if isinstance(value, datetime):
        return clock.fmt(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _value(v) for k, v in value.items()}
    return value


def _dump(row, fields, common=COMMON):
    out = {}
    for key in common:
        out[key] = _value(row.get(key))
    for key in fields:
        out[key] = _value(row.get(key))
    return out


def seller(row):
    return _dump(row, SELLER_FIELDS)


def fulfillment_center(row):
    return _dump(row, FC_FIELDS)


def listing(row):
    return _dump(row, LISTING_FIELDS)


def quota(row):
    return _dump(row, QUOTA_FIELDS)


def plan(row):
    return _dump(row, PLAN_FIELDS)


def line_item(row):
    return _dump(row, LINE_ITEM_FIELDS)


def lot(row):
    out = _dump(row, LOT_FIELDS)
    out["age_days"] = lot_age_days(row)
    return out


def assessment(row):
    return _dump(row, ASSESSMENT_FIELDS, common=APPEND_ONLY)


def removal(row):
    return _dump(row, REMOVAL_FIELDS)


def claim(row):
    return _dump(row, CLAIM_FIELDS)


def forecast(row):
    return _dump(row, FORECAST_FIELDS, common=APPEND_ONLY)


def mcf_order(row):
    return _dump(row, MCF_ORDER_FIELDS)
