"""Payload factories — one per write endpoint, input fields only.

Every factory takes `**overrides` so a test can control exactly the values its
claim depends on and inherit sensible defaults for the rest.  Passing
``field=None`` removes the field from the payload entirely, which is how tests
exercise the required-field rule.
"""

from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


def _finish(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides, dropping any key explicitly overridden to None."""
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not None}


# ---------------------------------------------------------------------------
# Vendors and catalog items
# ---------------------------------------------------------------------------


def create_vendor_payload(**overrides) -> dict:
    return _finish(
        {
            "name": TEST_DEFAULTS["VENDOR_NAME"],
            "brand_code": TEST_DEFAULTS["BRAND_CODE"],
            "correction_budget_cents": TEST_DEFAULTS["CORRECTION_BUDGET_CENTS"],
        },
        overrides,
    )


def create_catalog_item_payload(vendor_id: str, **overrides) -> dict:
    return _finish(
        {
            "vendor_id": vendor_id,
            "sku": TEST_DEFAULTS["SKU"],
            "category_code": TEST_DEFAULTS["CATEGORY_CODE"],
            "brand_size_system": TEST_DEFAULTS["SIZE_SYSTEM"],
            "unit_price_cents": TEST_DEFAULTS["UNIT_PRICE_CENTS"],
        },
        overrides,
    )


def delist_item_payload(**overrides) -> dict:
    return _finish({"delist_reason_code": "MANUAL"}, overrides)


def pdp_enhancement_payload(**overrides) -> dict:
    return _finish(
        {
            "model_measurements_published": True,
            "detail_image_count": 4,
            "model_height_cm": 178,
            "model_worn_size_label": "M",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Measurement specifications
# ---------------------------------------------------------------------------


def size_point(
    size_label: str,
    sort_index: int,
    chest_mm: int,
    waist_mm: int,
    hip_mm: int,
    inseam_mm: int,
) -> dict:
    return {
        "size_label": size_label,
        "sort_index": sort_index,
        "chest_mm": chest_mm,
        "waist_mm": waist_mm,
        "hip_mm": hip_mm,
        "inseam_mm": inseam_mm,
    }


def grade_rule(
    measurement_point: str,
    increment_mm: int,
    tolerance_pct_bp: int,
    tolerance_abs_mm: int,
) -> dict:
    return {
        "measurement_point": measurement_point,
        "increment_mm": increment_mm,
        "tolerance_pct_bp": tolerance_pct_bp,
        "tolerance_abs_mm": tolerance_abs_mm,
    }


# A two-point run whose chest step is exactly the declared 40 mm increment, so
# verification finds no violation.
CLEAN_TWO_POINT_RUN: List[dict] = [
    size_point("S", 0, 840, 760, 880, 710),
    size_point("M", 1, 880, 800, 920, 720),
]

# The same run with the larger size's chest 86 mm above the smaller one, a
# deviation of 46 mm against a 5 mm enforced tolerance.
VIOLATING_TWO_POINT_RUN: List[dict] = [
    size_point("S", 0, 840, 760, 880, 710),
    size_point("M", 1, 940, 800, 920, 720),
]

CHEST_ONLY_GRADE_RULES: List[dict] = [grade_rule("CHEST", 40, 1250, 3)]


def create_measurement_spec_payload(item_id: str, **overrides) -> dict:
    return _finish(
        {
            "item_id": item_id,
            "size_system": TEST_DEFAULTS["SIZE_SYSTEM"],
            "base_size_label": "S",
            "fabric_stretch_class": "RIGID",
            "size_points": [dict(p) for p in CLEAN_TWO_POINT_RUN],
            "grade_rules": [dict(r) for r in CHEST_ONLY_GRADE_RULES],
        },
        overrides,
    )


def resubmit_measurement_spec_payload(
    size_points: Optional[List[dict]] = None, **overrides
) -> dict:
    return _finish(
        {
            "size_points": [dict(p) for p in (size_points or CLEAN_TWO_POINT_RUN)],
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Size charts and mappings
# ---------------------------------------------------------------------------


def chart_row(
    size_label: str,
    sort_index: int,
    body_chest_min_mm: int,
    body_chest_max_mm: int,
    body_waist_min_mm: int,
    body_waist_max_mm: int,
    conversion_us_alpha: str,
    conversion_us_numeric: str,
    conversion_eu: str,
    conversion_uk: str,
) -> dict:
    return {
        "size_label": size_label,
        "sort_index": sort_index,
        "body_chest_min_mm": body_chest_min_mm,
        "body_chest_max_mm": body_chest_max_mm,
        "body_waist_min_mm": body_waist_min_mm,
        "body_waist_max_mm": body_waist_max_mm,
        "conversion_us_alpha": conversion_us_alpha,
        "conversion_us_numeric": conversion_us_numeric,
        "conversion_eu": conversion_eu,
        "conversion_uk": conversion_uk,
    }


TWO_ROW_CHART: List[dict] = [
    chart_row("S", 0, 820, 859, 740, 779, "S", "2", "34", "6"),
    chart_row("M", 1, 860, 899, 780, 819, "M", "4", "36", "8"),
]

FIVE_ROW_CHART: List[dict] = [
    chart_row("XS", 0, 780, 819, 700, 739, "XS", "0", "32", "4"),
    chart_row("S", 1, 820, 859, 740, 779, "S", "2", "34", "6"),
    chart_row("M", 2, 860, 899, 780, 819, "M", "4", "36", "8"),
    chart_row("L", 3, 900, 939, 820, 859, "L", "6", "38", "10"),
    chart_row("XL", 4, 940, 979, 860, 899, "XL", "8", "40", "12"),
]


def create_size_chart_payload(**overrides) -> dict:
    return _finish(
        {
            "chart_code": TEST_DEFAULTS["CHART_CODE"],
            "size_system": TEST_DEFAULTS["SIZE_SYSTEM"],
            "category_code": TEST_DEFAULTS["CATEGORY_CODE"],
            "rows": [dict(r) for r in TWO_ROW_CHART],
        },
        overrides,
    )


def retire_size_chart_payload(**overrides) -> dict:
    return _finish({"retire_reason_code": "DATA_QUALITY"}, overrides)


def size_label_pair(spec_size_label: str, chart_size_label: str) -> dict:
    return {"spec_size_label": spec_size_label, "chart_size_label": chart_size_label}


def create_size_chart_mapping_payload(
    item_id: str,
    chart_id: str,
    expected_item_version: int,
    size_label_pairs: Optional[List[dict]] = None,
    **overrides,
) -> dict:
    return _finish(
        {
            "item_id": item_id,
            "chart_id": chart_id,
            "expected_item_version": expected_item_version,
            "size_label_pairs": size_label_pairs
            or [size_label_pair("S", "S"), size_label_pair("M", "M")],
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Shoppers, policy and purchases
# ---------------------------------------------------------------------------


def create_customer_profile_payload(**overrides) -> dict:
    return _finish({"email": "shopper@example.com"}, overrides)


def create_return_policy_payload(**overrides) -> dict:
    return _finish(
        {
            "category_code": TEST_DEFAULTS["CATEGORY_CODE"],
            "window_days": TEST_DEFAULTS["WINDOW_DAYS"],
            "restocking_applies": True,
            "non_refundable_shipping": False,
            "effective_from": TEST_DEFAULTS["POLICY_EFFECTIVE_FROM"],
        },
        overrides,
    )


def create_return_policy_override_payload(
    expected_customer_profile_version: int, **overrides
) -> dict:
    return _finish(
        {
            "category_code": TEST_DEFAULTS["CATEGORY_CODE"],
            "window_days": 45,
            "restocking_applies": False,
            "non_refundable_shipping": False,
            "effective_from": TEST_DEFAULTS["POLICY_EFFECTIVE_FROM"],
            "expected_customer_profile_version": expected_customer_profile_version,
        },
        overrides,
    )


def create_order_line_payload(
    customer_profile_id: str, item_id: str, **overrides
) -> dict:
    return _finish(
        {
            "customer_profile_id": customer_profile_id,
            "item_id": item_id,
            "size_label": "M",
            "quantity": 1,
            "unit_price_cents": TEST_DEFAULTS["UNIT_PRICE_CENTS"],
            "shipping_allocated_cents": 0,
            "delivered_at": TEST_DEFAULTS["DELIVERED_AT"],
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Return cases
# ---------------------------------------------------------------------------


def create_return_case_payload(order_line_id: str, **overrides) -> dict:
    return _finish(
        {
            "order_line_id": order_line_id,
            "requested_reason_code": "FIT_TOO_SMALL",
        },
        overrides,
    )


def classify_return_case_payload(reason_code: str = "FIT_TOO_SMALL", **overrides) -> dict:
    return _finish({"reason_code": reason_code}, overrides)


def resolve_return_case_payload(item_condition: str = "RESELLABLE_A", **overrides) -> dict:
    return _finish({"item_condition": item_condition}, overrides)


def void_return_case_payload(**overrides) -> dict:
    return _finish({"void_reason": "AUDIT_REVERSAL"}, overrides)


# ---------------------------------------------------------------------------
# Fit feedback
# ---------------------------------------------------------------------------


def create_fit_feedback_payload(
    item_id: str, customer_profile_id: str, **overrides
) -> dict:
    return _finish(
        {
            "item_id": item_id,
            "customer_profile_id": customer_profile_id,
            "purchased_size_label": "M",
            "fit_verdict": "TRUE_TO_SIZE",
        },
        overrides,
    )


def retract_fit_feedback_payload(**overrides) -> dict:
    return _finish({"retract_reason": "AUTHOR_WITHDRAWN"}, overrides)


# ---------------------------------------------------------------------------
# Levers and deployments
# ---------------------------------------------------------------------------


def create_intervention_payload(**overrides) -> dict:
    return _finish(
        {
            "name": "Chart standardization wave 1",
            "lever": "SIZE_CHART_STANDARDIZATION",
            "unit_cost_cents": 2000,
        },
        overrides,
    )


def create_intervention_deployment_payload(
    intervention_id: str, item_id: str, **overrides
) -> dict:
    return _finish(
        {
            "intervention_id": intervention_id,
            "item_id": item_id,
            "window_start": "2026-07-01T00:00:00Z",
            "window_end": "2026-08-01T00:00:00Z",
            "spend_cents": 2000,
        },
        overrides,
    )


def terminate_deployment_payload(**overrides) -> dict:
    return _finish({"terminated_reason_code": "MANUAL_STOP"}, overrides)
