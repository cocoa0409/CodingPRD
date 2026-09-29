"""
Request-payload builders.

Each builder produces a complete, in-range payload for one endpoint and accepts
keyword overrides so a test can perturb exactly one field.  Passing
``field=None`` removes the field from the payload, which is how the omission
cases are built.
"""

from .constants import (
    APPAREL_MIN_ACCURACY_PCT,
    APPAREL_TOLERANCE_UNITS,
    APPAREL_TOLERANCE_VALUE_CENTS,
    APPAREL_UPLIFT_BPS,
    DEFAULT_EPC_PREFIX,
    DEFAULT_EPC_PREFIX_LENGTH,
    ELEC_MIN_ACCURACY_PCT,
    ELEC_TOLERANCE_UNITS,
    ELEC_TOLERANCE_VALUE_CENTS,
    ELEC_UPLIFT_BPS,
    HOME_MIN_ACCURACY_PCT,
    HOME_TOLERANCE_UNITS,
    HOME_TOLERANCE_VALUE_CENTS,
    HOME_UPLIFT_BPS,
    PAN_UNIT_COST_CENTS,
    PERIOD_END,
    PERIOD_SALES_AT_COST_CENTS,
    PERIOD_START,
    SOFA_UNIT_COST_CENTS,
    TEE1_UNIT_COST_CENTS,
    TEE2_UNIT_COST_CENTS,
    TV_UNIT_COST_CENTS,
    WINDOW_END,
    WINDOW_START,
)


def _merge(base: dict, overrides: dict) -> dict:
    payload = dict(base)
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
def apparel_category_payload(**overrides) -> dict:
    return _merge(
        {
            "code": "APPAREL",
            "name": "Apparel",
            "count_cadence_days": 30,
            "variance_tolerance_units": APPAREL_TOLERANCE_UNITS,
            "variance_tolerance_value_cents": APPAREL_TOLERANCE_VALUE_CENTS,
            "min_accuracy_pct": APPAREL_MIN_ACCURACY_PCT,
            "landed_cost_uplift_bps": APPAREL_UPLIFT_BPS,
            "reader_mode_required": "EITHER",
            "auto_correct_negative": True,
        },
        overrides,
    )


def home_category_payload(**overrides) -> dict:
    return _merge(
        {
            "code": "HOME",
            "name": "Home",
            "count_cadence_days": 30,
            "variance_tolerance_units": HOME_TOLERANCE_UNITS,
            "variance_tolerance_value_cents": HOME_TOLERANCE_VALUE_CENTS,
            "min_accuracy_pct": HOME_MIN_ACCURACY_PCT,
            "landed_cost_uplift_bps": HOME_UPLIFT_BPS,
            "reader_mode_required": "EITHER",
            "auto_correct_negative": True,
        },
        overrides,
    )


def elec_category_payload(**overrides) -> dict:
    return _merge(
        {
            "code": "ELEC",
            "name": "Electronics",
            "count_cadence_days": 14,
            "variance_tolerance_units": ELEC_TOLERANCE_UNITS,
            "variance_tolerance_value_cents": ELEC_TOLERANCE_VALUE_CENTS,
            "min_accuracy_pct": ELEC_MIN_ACCURACY_PCT,
            "landed_cost_uplift_bps": ELEC_UPLIFT_BPS,
            "reader_mode_required": "HANDHELD",
            "auto_correct_negative": False,
        },
        overrides,
    )


def toys_category_payload(**overrides) -> dict:
    return _merge(
        {
            "code": "TOYS",
            "name": "Toys",
            "count_cadence_days": 30,
            "variance_tolerance_units": 3,
            "variance_tolerance_value_cents": 9000,
            "min_accuracy_pct": 96.00,
            "landed_cost_uplift_bps": 500,
            "reader_mode_required": "EITHER",
            "auto_correct_negative": True,
        },
        overrides,
    )


def store_payload(**overrides) -> dict:
    return _merge(
        {
            "code": "S100",
            "name": "Store 100",
            "reader_capability": "BOTH",
            "overhead_reader_capacity": 2,
        },
        overrides,
    )


def handheld_only_store_payload(**overrides) -> dict:
    return _merge(
        {
            "code": "S200",
            "name": "Store 200",
            "reader_capability": "HANDHELD_ONLY",
            "overhead_reader_capacity": 0,
        },
        overrides,
    )


def vendor_payload(**overrides) -> dict:
    return _merge({"code": "VEND1", "name": "Vendor One"}, overrides)


def counter_firm_payload(**overrides) -> dict:
    return _merge(
        {
            "code": "CF1",
            "name": "Counting Firm One",
            "certification_level": "TIER_1",
            "max_lines_per_pass": 500,
        },
        overrides,
    )


def item_payload(category_id: str, vendor_id: str, **overrides) -> dict:
    return _merge(
        {
            "category_id": category_id,
            "primary_vendor_id": vendor_id,
            "sku": "TEE-001",
            "description": "Crew tee",
            "unit_cost_cents": TEE1_UNIT_COST_CENTS,
            "retail_price_cents": 2999,
            "tag_encoding_scheme": "SGTIN_96",
            "epc_prefix_length": DEFAULT_EPC_PREFIX_LENGTH,
            "tag_required": True,
        },
        overrides,
    )


def _item_variant(category_id: str, vendor_id: str, defaults: dict, overrides: dict) -> dict:
    """A named SKU variant whose caller overrides always win over the variant's own."""
    merged = dict(defaults)
    merged.update(overrides)
    return item_payload(category_id, vendor_id, **merged)


def tee2_item_payload(category_id: str, vendor_id: str, **overrides) -> dict:
    return _item_variant(
        category_id,
        vendor_id,
        {
            "sku": "TEE-002",
            "description": "V-neck tee",
            "unit_cost_cents": TEE2_UNIT_COST_CENTS,
            "retail_price_cents": 4999,
        },
        overrides,
    )


def pan_item_payload(category_id: str, vendor_id: str, **overrides) -> dict:
    return _item_variant(
        category_id,
        vendor_id,
        {
            "sku": "PAN-01",
            "description": "Saute pan",
            "unit_cost_cents": PAN_UNIT_COST_CENTS,
            "retail_price_cents": 2999,
        },
        overrides,
    )


def sofa_item_payload(category_id: str, vendor_id: str, **overrides) -> dict:
    return _item_variant(
        category_id,
        vendor_id,
        {
            "sku": "SOFA-01",
            "description": "Two-seat sofa",
            "unit_cost_cents": SOFA_UNIT_COST_CENTS,
            "retail_price_cents": 9999,
        },
        overrides,
    )


def tv_item_payload(category_id: str, vendor_id: str, **overrides) -> dict:
    return _item_variant(
        category_id,
        vendor_id,
        {
            "sku": "TV-040",
            "description": "40 inch panel",
            "unit_cost_cents": TV_UNIT_COST_CENTS,
            "retail_price_cents": 79999,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Operational data
# ---------------------------------------------------------------------------
def stock_position_payload(store_id: str, item_id: str, **overrides) -> dict:
    return _merge(
        {
            "store_id": store_id,
            "item_id": item_id,
            "baseline_on_hand_units": 100,
            "reserved_units": 0,
        },
        overrides,
    )


def tag_batch_payload(vendor_id: str, item_id: str, store_id: str, **overrides) -> dict:
    return _merge(
        {
            "vendor_id": vendor_id,
            "item_id": item_id,
            "destination_store_id": store_id,
            "quantity_encoded": 1000,
        },
        overrides,
    )


def encode_payload(**overrides) -> dict:
    return _merge(
        {"encoding_scheme": "SGTIN_96", "epc_prefix": DEFAULT_EPC_PREFIX}, overrides
    )


def verify_payload(**overrides) -> dict:
    return _merge(
        {
            "sampled_units": 50,
            "readable_units": 50,
            "duplicate_epc_count": 0,
            "unencoded_units": 0,
        },
        overrides,
    )


def count_schedule_payload(store_id: str, category_id: str, **overrides) -> dict:
    return _merge(
        {
            "store_id": store_id,
            "category_id": category_id,
            "reader_mode": "HANDHELD",
            "first_due_date": "2026-08-01",
            "cadence_days": 30,
        },
        overrides,
    )


def count_task_payload(count_schedule_id: str, **overrides) -> dict:
    return _merge(
        {
            "count_schedule_id": count_schedule_id,
            "reader_mode": "HANDHELD",
            "window_start": WINDOW_START,
            "window_end": WINDOW_END,
        },
        overrides,
    )


def count_line_payload(item_id: str, counted_units: int, **overrides) -> dict:
    return _merge(
        {
            "item_id": item_id,
            "counted_units": counted_units,
            "read_mode_used": "HANDHELD",
        },
        overrides,
    )


def shrink_period_payload(store_id: str, **overrides) -> dict:
    return _merge(
        {
            "store_id": store_id,
            "period_start": PERIOD_START,
            "period_end": PERIOD_END,
            "sales_at_cost_cents": PERIOD_SALES_AT_COST_CENTS,
        },
        overrides,
    )


def adjustment_payload(delta_units: int, expected_version: int, **overrides) -> dict:
    return _merge(
        {
            "delta_units": delta_units,
            "reason_code": "COUNT_VARIANCE",
            "expected_stock_position_version": expected_version,
        },
        overrides,
    )


def propose_cause_payload(root_cause: str, expected_version: int, **overrides) -> dict:
    return _merge(
        {
            "proposed_root_cause": root_cause,
            "evidence_note": "Exit-door read log reviewed against the tag population",
            "expected_investigation_version": expected_version,
        },
        overrides,
    )


def assign_payload(investigator_id: str, **overrides) -> dict:
    return _merge({"assigned_investigator_id": investigator_id}, overrides)


def physical_inventory_payload(store_id: str, counter_firm_id: str, **overrides) -> dict:
    return _merge(
        {
            "store_id": store_id,
            "counter_firm_id": counter_firm_id,
            "scheduled_start_date": "2026-09-10",
            "scheduled_end_date": "2026-09-12",
            "recount_threshold_bps": 150,
        },
        overrides,
    )


def physical_line_payload(item_id: str, counted_units: int, expected_version: int, **overrides) -> dict:
    return _merge(
        {
            "item_id": item_id,
            "counted_units": counted_units,
            "expected_physical_inventory_version": expected_version,
        },
        overrides,
    )


def chargeback_payload(shrink_period_id: str, **overrides) -> dict:
    return _merge({"shrink_period_id": shrink_period_id}, overrides)


def chargeback_credit_payload(credit_cents: int, **overrides) -> dict:
    return _merge(
        {"credit_cents": credit_cents, "note": "Rebuttal accepted"}, overrides
    )
