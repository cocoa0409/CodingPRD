"""Domain assertion helpers.

Two families live here.  The `assert_<entity>_shape` helpers check the structural
promises the PRD makes about every representation of a resource type: which keys
are present, which are absent, and which system-managed properties carry the
formats described in PRD 2.4.  The remaining helpers assert relationships the PRD
states between several fields of one payload, or between a payload and a table of
declared rates, so that a test can name a consequence once instead of restating
it as a pile of equality checks.

None of these helpers invent expectations.  A test that needs a specific number
still asserts that number itself; these helpers only cover statements the PRD
makes uniformly across a whole resource type.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ABUSE_BLOCKED_STRIKES,
    ABUSE_FEE_MULTIPLIER_BP,
    ABUSE_RATE_BLOCK_BP,
    ABUSE_RATE_MIN_LINES,
    ABUSE_RESTRICTED_STRIKES,
    ABUSE_WATCH_STRIKES,
    CHRONIC_THRESHOLD_BP,
    COST_COMPONENT_ORDER,
    EXPECTATION_WEIGHT_BP,
    FIT_WEIGHT_BP,
    FREIGHT_INBOUND_CENTS,
    HANDLING_MINUTES,
    LABOR_RATE_CENTS_PER_MIN,
    MARKDOWN_PCT_BP,
    MIN_EFFECTIVE_WINDOW_DAYS,
    MIN_FIT_RETURNS_CHRONIC,
    MIN_FIT_RETURNS_WATCH,
    NEUTRAL_FEE_MULTIPLIER_BP,
    PAYMENT_FEE_BP,
    POLICY_CLASS_DELTA_DAYS,
    REFURB_PCT_BP,
    RESTOCK_TIER_0_BP,
    RESTOCK_TIER_1_BP,
    RESTOCK_TIER_1_CENTS,
    RESTOCK_TIER_2_BP,
    RESTOCK_TIER_2_CENTS,
    STRETCH_MULTIPLIER_PCT,
    TOLERANCE_CEILING_MM,
    VENDOR_CHARGEBACK_PCT_BP,
    WATCH_THRESHOLD_BP,
)

# ---------------------------------------------------------------------------
# Common resource properties (PRD 2.4)
# ---------------------------------------------------------------------------

# The four properties every resource carries, except the append-only ledger line.
COMMON_FIELDS = ("id", "created_at", "updated_at", "version")

# The append-only ledger line carries only these two of the four.
LEDGER_COMMON_FIELDS = ("id", "created_at")


def assert_common_fields(data: dict) -> None:
    """`id` is a UUID, `created_at` and `updated_at` are ISO 8601 UTC instants,
    and `version` is an integer that starts at 1."""
    for field in COMMON_FIELDS:
        assert field in data, f"expected common property {field!r} in {sorted(data)}"
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data['id']!r}"
    assert is_iso8601_timestamp(
        data["created_at"]
    ), f"created_at is not ISO 8601: {data['created_at']!r}"
    assert is_iso8601_timestamp(
        data["updated_at"]
    ), f"updated_at is not ISO 8601: {data['updated_at']!r}"
    assert isinstance(data["version"], int) and not isinstance(data["version"], bool)
    assert data["version"] >= 1, f"version must start at 1, saw {data['version']!r}"


def assert_ledger_common_fields(data: dict) -> None:
    """A cost posting carries `id` and `created_at` only.  `updated_at` and
    `version` must be absent from its representation rather than present and
    null."""
    for field in LEDGER_COMMON_FIELDS:
        assert field in data, f"expected {field!r} in {sorted(data)}"
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data['id']!r}"
    assert is_iso8601_timestamp(
        data["created_at"]
    ), f"created_at is not ISO 8601: {data['created_at']!r}"
    assert "updated_at" not in data, "a cost posting must not expose updated_at"
    assert "version" not in data, "a cost posting must not expose version"


def assert_fields_present(data: dict, fields) -> None:
    missing = [f for f in fields if f not in data]
    assert not missing, f"missing fields {missing} in {sorted(data)}"


def assert_optional_field_is_null(data: dict, field: str) -> None:
    """An optional field that has not been set is present and null, not absent."""
    assert field in data, f"optional field {field!r} must be present, saw {sorted(data)}"
    assert data[field] is None, f"expected {field!r} null, saw {data[field]!r}"


# ---------------------------------------------------------------------------
# Per-entity shape checks
# ---------------------------------------------------------------------------

VENDOR_FIELDS = (
    "name",
    "brand_code",
    "correction_budget_cents",
    "correction_spend_cents",
    "correction_round_count",
    "quality_chargeback_count",
    "reliability_score_bp",
    "status",
)

CATALOG_ITEM_FIELDS = (
    "vendor_id",
    "sku",
    "category_code",
    "brand_size_system",
    "unit_price_cents",
    "listing_status",
    "fit_readiness",
    "fit_watch_state",
    "model_measurements_published",
    "model_height_cm",
    "model_worn_size_label",
    "detail_image_count",
    "pdp_review_required",
    "units_sold_count",
    "fit_return_count",
    "expectation_return_count",
    "total_return_count",
    "fit_return_rate_bp",
    "expectation_return_rate_bp",
    "chronic_return_score_bp",
    "return_cost_accrued_cents",
    "fit_signal_weight_total",
    "active_fit_feedback_count",
    "delist_reason_code",
)

MEASUREMENT_SPEC_FIELDS = (
    "item_id",
    "revision_round",
    "status",
    "size_system",
    "base_size_label",
    "fabric_stretch_class",
    "size_points",
    "grade_rules",
    "violation_count",
    "first_violation_point",
    "first_violation_from_size_label",
    "tolerance_applied_mm",
    "correction_reason",
    "verified_by_user_id",
    "verified_at",
)

SIZE_CHART_FIELDS = (
    "chart_code",
    "size_system",
    "category_code",
    "status",
    "rows",
    "row_count",
    "median_row_index",
    "retire_reason_code",
)

SIZE_CHART_MAPPING_FIELDS = (
    "item_id",
    "chart_id",
    "size_label_pairs",
    "mapped_row_count",
    "spec_size_point_count",
    "coverage_bp",
    "unmapped_size_labels",
    "status",
    "superseded_reason",
)

CUSTOMER_PROFILE_FIELDS = (
    "email",
    "tier",
    "purchase_line_count",
    "return_case_count",
    "change_of_mind_count",
    "return_rate_bp",
    "abuse_strike_count",
    "abuse_status",
    "policy_class",
    "refunded_total_cents",
)

ORDER_LINE_FIELDS = (
    "customer_profile_id",
    "item_id",
    "size_label",
    "quantity",
    "unit_price_cents",
    "shipping_allocated_cents",
    "delivered_at",
    "gross_line_cents",
    "status",
)

RETURN_CASE_FIELDS = (
    "order_line_id",
    "requested_reason_code",
    "reason_code",
    "reason_family",
    "status",
    "effective_policy_id",
    "effective_window_days",
    "return_deadline_at",
    "requested_at",
    "item_condition",
    "restocking_fee_cents",
    "refund_amount_cents",
    "total_cost_cents",
    "classified_by_user_id",
    "resolved_by_user_id",
    "void_reason",
)

RETURN_COST_POSTING_FIELDS = (
    "return_case_id",
    "component",
    "amount_cents",
    "posting_kind",
    "reversed_component",
)

FIT_FEEDBACK_FIELDS = (
    "item_id",
    "customer_profile_id",
    "purchased_size_label",
    "fit_verdict",
    "comment",
    "verdict_offset_centi",
    "signal_weight",
    "status",
    "retract_reason",
)

RETURN_POLICY_FIELDS = (
    "scope",
    "customer_profile_id",
    "category_code",
    "window_days",
    "restocking_applies",
    "non_refundable_shipping",
    "effective_from",
    "effective_to",
)

INTERVENTION_FIELDS = (
    "name",
    "lever",
    "unit_cost_cents",
    "deployment_count",
    "measured_deployment_count",
    "gross_savings_cents",
    "spend_cents",
    "net_savings_cents",
    "funding_posture",
)

INTERVENTION_DEPLOYMENT_FIELDS = (
    "intervention_id",
    "item_id",
    "window_start",
    "window_end",
    "spend_cents",
    "status",
    "baseline_units_count",
    "baseline_return_rate_bp",
    "window_units_count",
    "measured_return_rate_bp",
    "avoided_return_count",
    "attributed_savings_cents",
    "terminated_reason_code",
)


def assert_vendor_shape(data: dict) -> None:
    assert_common_fields(data)
    assert_fields_present(data, VENDOR_FIELDS)


def assert_catalog_item_shape(data: dict) -> None:
    assert_common_fields(data)
    assert_fields_present(data, CATALOG_ITEM_FIELDS)


def assert_measurement_spec_shape(data: dict) -> None:
    assert_common_fields(data)
    assert_fields_present(data, MEASUREMENT_SPEC_FIELDS)


def assert_size_chart_shape(data: dict) -> None:
    assert_common_fields(data)
    assert_fields_present(data, SIZE_CHART_FIELDS)


def assert_size_chart_mapping_shape(data: dict) -> None:
    assert_common_fields(data)
    assert_fields_present(data, SIZE_CHART_MAPPING_FIELDS)


def assert_customer_profile_shape(data: dict) -> None:
    assert_common_fields(data)
    assert_fields_present(data, CUSTOMER_PROFILE_FIELDS)


def assert_order_line_shape(data: dict) -> None:
    assert_common_fields(data)
    assert_fields_present(data, ORDER_LINE_FIELDS)


def assert_return_case_shape(data: dict) -> None:
    assert_common_fields(data)
    assert_fields_present(data, RETURN_CASE_FIELDS)


def assert_return_cost_posting_shape(data: dict) -> None:
    """A ledger line's structural promise, including the two absent keys."""
    assert_ledger_common_fields(data)
    assert_fields_present(data, RETURN_COST_POSTING_FIELDS)


def assert_fit_feedback_shape(data: dict) -> None:
    assert_common_fields(data)
    assert_fields_present(data, FIT_FEEDBACK_FIELDS)


def assert_return_policy_shape(data: dict) -> None:
    assert_common_fields(data)
    assert_fields_present(data, RETURN_POLICY_FIELDS)


def assert_intervention_shape(data: dict) -> None:
    assert_common_fields(data)
    assert_fields_present(data, INTERVENTION_FIELDS)


def assert_intervention_deployment_shape(data: dict) -> None:
    assert_common_fields(data)
    assert_fields_present(data, INTERVENTION_DEPLOYMENT_FIELDS)


# ---------------------------------------------------------------------------
# Field-to-field relationships stated by the PRD
# ---------------------------------------------------------------------------


def assert_gross_line_consistent(line: dict) -> None:
    """The gross line amount is the unit price multiplied by the quantity.  The
    allocated shipping is carried alongside it and never folded into it."""
    expected = line["unit_price_cents"] * line["quantity"]
    assert line["gross_line_cents"] == expected, (
        f"gross_line_cents {line['gross_line_cents']} != "
        f"{line['unit_price_cents']} * {line['quantity']} = {expected}"
    )


def assert_coverage_consistent(mapping: dict) -> None:
    """Coverage is the mapped row count multiplied by 10,000, divided by the
    specification's size-point count, with any fraction discarded, and is 0 when
    that count is 0."""
    mapped = mapping["mapped_row_count"]
    total = mapping["spec_size_point_count"]
    expected = 0 if total == 0 else (mapped * 10000) // total
    assert mapping["coverage_bp"] == expected, (
        f"coverage_bp {mapping['coverage_bp']} != floor("
        f"{mapped} * 10000 / {total}) = {expected}"
    )


def assert_net_savings_consistent(payload: dict) -> None:
    """Net savings is gross savings minus spend."""
    expected = payload["gross_savings_cents"] - payload["spend_cents"]
    assert payload["net_savings_cents"] == expected, (
        f"net_savings_cents {payload['net_savings_cents']} != "
        f"{payload['gross_savings_cents']} - {payload['spend_cents']} = {expected}"
    )


def assert_no_verification_verdict(spec: dict) -> None:
    """Before a verification has been decided, the verdict fields are present and
    null and no violation has been counted."""
    assert spec["violation_count"] == 0, spec["violation_count"]
    assert_optional_field_is_null(spec, "first_violation_point")
    assert_optional_field_is_null(spec, "first_violation_from_size_label")
    assert_optional_field_is_null(spec, "verified_by_user_id")
    assert_optional_field_is_null(spec, "verified_at")


# ---------------------------------------------------------------------------
# The append-only cost ledger (PRD 2.10)
# ---------------------------------------------------------------------------


def cost_postings_by_component(postings: List[dict]) -> Dict[str, int]:
    """Collapse a ledger listing into component -> summed amount."""
    totals: Dict[str, int] = {}
    for row in postings:
        totals[row["component"]] = totals.get(row["component"], 0) + row["amount_cents"]
    return totals


def assert_posting_components(postings: List[dict], expected: Dict[str, int]) -> None:
    """Every named component carries exactly the stated amount, and no other
    component appears."""
    actual = cost_postings_by_component(postings)
    assert actual == expected, f"ledger components {actual} != {expected}"


def assert_postings_in_declared_order(postings: List[dict]) -> None:
    """Postings of one resolution are written in the declared component order."""
    order = {name: i for i, name in enumerate(COST_COMPONENT_ORDER)}
    seen = [order[row["component"]] for row in postings]
    assert seen == sorted(seen), (
        "postings are not in the declared component order: "
        f"{[row['component'] for row in postings]}"
    )


def assert_ledger_sums_to(postings: List[dict], expected_cents: int) -> None:
    total = sum(row["amount_cents"] for row in postings)
    assert total == expected_cents, f"ledger sum {total} != {expected_cents}"


def assert_every_original_is_reversed(postings: List[dict]) -> None:
    """After a void, each original posting is offset by a reversal naming the same
    component with the negated amount, and the ledger nets to zero."""
    originals = [r for r in postings if r["posting_kind"] == "ORIGINAL"]
    reversals = [r for r in postings if r["posting_kind"] == "REVERSAL"]
    assert len(reversals) == len(originals), (
        f"{len(originals)} original postings but {len(reversals)} reversals"
    )
    for original in originals:
        match = [
            r
            for r in reversals
            if r["reversed_component"] == original["component"]
            and r["amount_cents"] == -original["amount_cents"]
        ]
        assert match, (
            f"no reversal offsetting {original['component']} "
            f"{original['amount_cents']}"
        )
    assert_ledger_sums_to(postings, 0)


# ---------------------------------------------------------------------------
# Cost derivations (PRD 2.6, 3.8)
# ---------------------------------------------------------------------------


def round_half_up(numerator: int, denominator: int) -> int:
    """Round a non-negative ratio half away from zero, as PRD 2.6 requires for
    money and rate results."""
    if numerator < 0:
        return -((-numerator * 2 + denominator) // (denominator * 2))
    return (numerator * 2 + denominator) // (denominator * 2)


def apply_bp(amount_cents: int, rate_bp: int) -> int:
    """A basis-point share of an amount, rounded half up."""
    return round_half_up(amount_cents * rate_bp, 10000)


def expected_processing_labor_cents(reason_family: str) -> int:
    """The labor component: declared handling minutes times the hourly rate
    expressed per minute."""
    return HANDLING_MINUTES[reason_family] * LABOR_RATE_CENTS_PER_MIN


def restocking_tier_bp(gross_line_cents: int) -> int:
    """The tier is keyed on the gross line amount and never on the refund: below
    5,000 cents is 0 basis points, 5,000 up to but not including 20,000 is 1,000,
    and 20,000 or more is 1,500."""
    if gross_line_cents < RESTOCK_TIER_1_CENTS:
        return RESTOCK_TIER_0_BP
    if gross_line_cents < RESTOCK_TIER_2_CENTS:
        return RESTOCK_TIER_1_BP
    return RESTOCK_TIER_2_BP


def expected_restocking_fee_cents(
    gross_line_cents: int,
    reason_family: str,
    restocking_applies: bool,
    abuse_status: str = "CLEAR",
    landing_status: str = "RESOLVED_REFUNDED",
) -> int:
    """A fee is actually withheld only when the reason family is change of mind,
    the frozen policy allows restocking, and the case lands refunded; the abuse
    multiplier is armed by `RESTRICTED` standing specifically."""
    if (
        reason_family != "CHANGE_OF_MIND"
        or not restocking_applies
        or landing_status != "RESOLVED_REFUNDED"
    ):
        return 0
    base = apply_bp(gross_line_cents, restocking_tier_bp(gross_line_cents))
    multiplier = (
        ABUSE_FEE_MULTIPLIER_BP
        if abuse_status == "RESTRICTED"
        else NEUTRAL_FEE_MULTIPLIER_BP
    )
    return apply_bp(base, multiplier)


def expected_refund_cents(
    gross_line_cents: int,
    shipping_allocated_cents: int,
    restocking_fee_cents: int,
    non_refundable_shipping: bool,
) -> int:
    """The refund: the gross line less the restocking fee, and less the allocated
    shipping when the governing policy makes shipping non-refundable, floored at
    zero."""
    refund = gross_line_cents - restocking_fee_cents
    if non_refundable_shipping:
        refund -= shipping_allocated_cents
    return max(refund, 0)


def expected_return_cost_components(
    category_code: str,
    reason_family: str,
    item_condition: str,
    gross_line_cents: int,
    refund_amount_cents: int,
) -> Dict[str, int]:
    """The six components of a refunded resolution.  Freight is a flat
    per-category charge, labor is minutes times the per-minute rate, refurb and
    markdown are shares of the gross keyed on the condition grade, the payment fee
    is a share of the refund rather than the gross, and the chargeback credit is
    written only for the quality family as the negation of a share of the gross —
    so a non-quality resolution writes five rows and a quality one writes six.
    Each component is rounded on its own before the sum is taken."""
    components = {
        "FREIGHT_INBOUND": FREIGHT_INBOUND_CENTS[category_code],
        "PROCESSING_LABOR": expected_processing_labor_cents(reason_family),
        "REFURB_REPACK": apply_bp(gross_line_cents, REFURB_PCT_BP[item_condition]),
        "MARKDOWN_LOSS": apply_bp(gross_line_cents, MARKDOWN_PCT_BP[item_condition]),
        "PAYMENT_FEE_UNRECOVERED": apply_bp(refund_amount_cents, PAYMENT_FEE_BP),
    }
    if reason_family == "QUALITY":
        components["VENDOR_CHARGEBACK_CREDIT"] = -apply_bp(
            gross_line_cents, VENDOR_CHARGEBACK_PCT_BP
        )
    return components


def expected_denied_cost_components(
    category_code: str, reason_family: str
) -> Dict[str, int]:
    """A denied resolution moves no money, so only the two components that the
    program incurs regardless of outcome are written."""
    return {
        "FREIGHT_INBOUND": FREIGHT_INBOUND_CENTS[category_code],
        "PROCESSING_LABOR": expected_processing_labor_cents(reason_family),
    }


# ---------------------------------------------------------------------------
# Derived standing (PRD 3.8)
# ---------------------------------------------------------------------------


def expected_rate_bp(count: int, denominator: int) -> int:
    """A rate in basis points with any fraction discarded, and 0 when the
    denominator is 0."""
    if denominator == 0:
        return 0
    return (count * 10000) // denominator


def expected_chronic_score_bp(
    fit_return_rate_bp: int, expectation_return_rate_bp: int
) -> int:
    """Three quarters weight on the fit rate and one quarter on the expectation
    rate, with any fraction discarded."""
    return (
        FIT_WEIGHT_BP * fit_return_rate_bp + EXPECTATION_WEIGHT_BP * expectation_return_rate_bp
    ) // 10000


def expected_fit_watch_state(chronic_score_bp: int, fit_return_count: int) -> str:
    """The classification is re-derived rather than latched, so it walks in both
    directions."""
    if chronic_score_bp >= CHRONIC_THRESHOLD_BP and fit_return_count >= MIN_FIT_RETURNS_CHRONIC:
        return "CHRONIC"
    if chronic_score_bp >= WATCH_THRESHOLD_BP and fit_return_count >= MIN_FIT_RETURNS_WATCH:
        return "WATCH"
    return "NORMAL"


def expected_abuse_status(
    abuse_strike_count: int, return_rate_bp: int, purchase_line_count: int
) -> str:
    """The blocking rule is not a strict ladder: a high enough return rate over
    enough purchases blocks a shopper who never earned a strike."""
    rate_rule = (
        return_rate_bp >= ABUSE_RATE_BLOCK_BP and purchase_line_count >= ABUSE_RATE_MIN_LINES
    )
    if abuse_strike_count >= ABUSE_BLOCKED_STRIKES or rate_rule:
        return "BLOCKED"
    if abuse_strike_count >= ABUSE_RESTRICTED_STRIKES:
        return "RESTRICTED"
    if abuse_strike_count >= ABUSE_WATCH_STRIKES:
        return "WATCH"
    return "CLEAR"


def expected_policy_class(abuse_status: str, tier: str) -> str:
    if abuse_status in ("RESTRICTED", "BLOCKED"):
        return "RESTRICTED_WINDOW"
    if tier == "PLUS" and abuse_status == "CLEAR":
        return "EXTENDED_WINDOW"
    return "STANDARD_WINDOW"


def expected_effective_window_days(policy_window_days: int, policy_class: str) -> int:
    """The governing policy's window shifted by the shopper's class, subject to the
    seven-day floor."""
    return max(
        policy_window_days + POLICY_CLASS_DELTA_DAYS[policy_class],
        MIN_EFFECTIVE_WINDOW_DAYS,
    )


# ---------------------------------------------------------------------------
# Grade tolerance (PRD 3.2)
# ---------------------------------------------------------------------------


def expected_tolerance_mm(
    increment_mm: int,
    tolerance_pct_bp: int,
    tolerance_abs_mm: int,
    measurement_point: str,
    fabric_stretch_class: str,
) -> int:
    """The enforced tolerance for one measurement point, resolved in the four
    declared steps and in that order: the percentage component rounded half up,
    the larger of it and the absolute allowance, that raw value capped downward to
    the point's ceiling, and finally the capped value scaled by the stretch class
    with any fraction discarded."""
    pct = apply_bp(increment_mm, tolerance_pct_bp)
    raw = max(tolerance_abs_mm, pct)
    capped = min(raw, TOLERANCE_CEILING_MM[measurement_point])
    return (capped * STRETCH_MULTIPLIER_PCT[fabric_stretch_class]) // 100


# ---------------------------------------------------------------------------
# Listing helpers
# ---------------------------------------------------------------------------


def ids_of(rows: List[dict]) -> List[str]:
    return [row["id"] for row in rows]


def assert_listing_contains_exactly(rows: List[dict], expected_ids: List[str]) -> None:
    assert ids_of(rows) == expected_ids, f"{ids_of(rows)} != {expected_ids}"


def assert_created_at_ascending(rows: List[dict]) -> None:
    """Every listing is ordered by creation instant, oldest first."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"listing is not oldest-first: {stamps}"


def find_by_id(rows: List[dict], row_id: str) -> Optional[Dict[str, Any]]:
    for row in rows:
        if row["id"] == row_id:
            return row
    return None
