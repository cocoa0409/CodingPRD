"""Values that land exactly on a threshold.

Two thresholds decide whether work is admitted or refused, and both are written as
inclusive comparisons.  A grade deviation equal to the enforced tolerance is not a
violation, and a mapping coverage equal to the publishing minimum is sufficient.
Each scenario is placed exactly on the line rather than near it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ApiClient,
    ApiErrorId,
    chart_row,
    grade_rule,
    is_iso8601_timestamp,
    make_fit_analyst_headers,
    size_label_pair,
    size_point,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx  # noqa: E402

# A five-size chest run graded by 40 millimetres whose M-to-L step is 45.  The
# deviation of 5 millimetres is exactly the tolerance the CHEST rule below resolves
# to, so the run sits on the threshold rather than either side of it.
EQUALITY_FIVE_SIZE_POINTS = [
    size_point("XS", 0, 800, 720, 840, 700),
    size_point("S", 1, 840, 760, 880, 710),
    size_point("M", 2, 880, 800, 920, 720),
    size_point("L", 3, 925, 845, 965, 730),
    size_point("XL", 4, 965, 885, 1005, 740),
]

CHEST_GRADE_RULES = [grade_rule("CHEST", 40, 1250, 3)]

FIVE_ROW_TOPS_CHART = [
    chart_row("XS", 0, 780, 819, 700, 739, "XS", "0", "32", "4"),
    chart_row("S", 1, 820, 859, 740, 779, "S", "2", "34", "6"),
    chart_row("M", 2, 860, 899, 780, 819, "M", "4", "36", "8"),
    chart_row("L", 3, 900, 944, 820, 864, "L", "6", "38", "10"),
    chart_row("XL", 4, 945, 984, 865, 904, "XL", "8", "40", "12"),
]

THREE_OF_FIVE_PAIRS = [
    size_label_pair("S", "S"),
    size_label_pair("M", "M"),
    size_label_pair("L", "L"),
]

FOUR_OF_FIVE_PAIRS = THREE_OF_FIVE_PAIRS + [size_label_pair("XL", "XL")]


def _build_submitted_spec_on_the_tolerance_line(api: ApiClient) -> dict:
    """A listed item under an unblemished brand whose submitted specification grades
    every chest step within the enforced tolerance and one step exactly at it."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    vendor = fx.create_vendor(
        api, name="Edgecase Mills", brand_code="EDGE", correction_budget_cents=10000
    )
    item = fx.list_item(
        api,
        fx.create_item(
            api,
            vendor["id"],
            sku="EDGE-TEE-01",
            category_code="TOPS",
            brand_size_system="US_ALPHA",
            unit_price_cents=2295,
        )["id"],
    )
    spec = fx.create_spec(
        api,
        item["id"],
        vendor["id"],
        size_system="US_ALPHA",
        base_size_label="M",
        fabric_stretch_class="RIGID",
        size_points=EQUALITY_FIVE_SIZE_POINTS,
        grade_rules=CHEST_GRADE_RULES,
    )
    spec = fx.submit_spec(api, spec["id"], vendor["id"])
    return {"vendor": vendor, "item": item, "spec": spec}


def test_a_chest_step_off_by_exactly_the_tolerance_is_not_a_violation(api):
    """PRD §3.2: "The check compares the absolute difference between that observed
    step and the rule's declared `increment_mm` against the enforced tolerance: a
    violation is recorded only when that absolute difference is **strictly greater**
    than the tolerance, so a deviation exactly equal to the tolerance passes."  The
    M-to-L chest step of 45 against a declared increment of 40 is off by 5, which is
    the enforced tolerance to the millimetre, so the walk finds nothing and the
    specification verifies with both first-violation fields empty.

    Design: Difficulty/boundary_precision_check/grade_tolerance_equality_verifies_specification
    """
    built = _build_submitted_spec_on_the_tolerance_line(api)

    assert built["spec"]["status"] == "SUBMITTED"

    spec = validate_success(
        api.verify_measurement_spec(built["spec"]["id"], make_fit_analyst_headers())
    )

    assert spec["status"] == "VERIFIED"
    assert spec["violation_count"] == 0
    assert spec["first_violation_point"] is None
    assert spec["first_violation_from_size_label"] is None


def test_the_run_records_the_five_millimetre_tolerance_the_rigid_class_resolved(api):
    """PRD §3.2: "Finally the capped value is scaled by the stretch class and floored
    to a whole millimetre: `RIGID` scales by 100 percent, `STRETCH` by 150 percent,
    and `HIGH_STRETCH` by 200 percent, so the enforced tolerance is the capped value
    multiplied by that percentage, divided by 100, with any fraction discarded."  The
    percentage component of 1,250 basis points on a 40-millimetre increment rounds to
    5, which beats the 3-millimetre absolute allowance and sits far below the
    25-millimetre chest ceiling, and a rigid fabric leaves that 5 untouched.

    Design: Difficulty/boundary_precision_check/grade_tolerance_equality_verifies_specification
    """
    built = _build_submitted_spec_on_the_tolerance_line(api)

    spec = fx.verify_spec(api, built["spec"]["id"])

    assert spec["tolerance_applied_mm"] == [
        {"measurement_point": "CHEST", "tolerance_mm": 5}
    ]


def test_the_clean_pass_stamps_the_analyst_and_never_bills_the_brand(api):
    """PRD §3.2: "`verified_by_user_id` records the acting `X-User-ID` and
    `verified_at` records the logical clock instant."  A specification that clears
    verification on its first pass is still on revision round 0 with no correction
    reason, and the brand that submitted it has been charged for no rounds at all, so
    its reliability is untouched at a perfect 10,000 basis points.

    Design: Difficulty/boundary_precision_check/grade_tolerance_equality_verifies_specification
    """
    built = _build_submitted_spec_on_the_tolerance_line(api)

    spec = fx.verify_spec(api, built["spec"]["id"])

    assert spec["verified_by_user_id"] == "analyst-7"
    assert is_iso8601_timestamp(spec["verified_at"])
    assert spec["verified_at"].startswith("2026-06-01T00:00:00")
    assert spec["revision_round"] == 0
    assert spec["correction_reason"] is None

    vendor = fx.read_vendor(api, built["vendor"]["id"])
    assert vendor["correction_round_count"] == 0
    assert vendor["correction_spend_cents"] == 0
    assert vendor["reliability_score_bp"] == 10000
    assert vendor["status"] == "ACTIVE"

    item = fx.read_item(api, built["item"]["id"])
    assert item["fit_readiness"] == "UNVERIFIED"


def _build_item_awaiting_a_mapping(api: ApiClient) -> dict:
    """A listed item with a verified five-point specification, a complete product
    page and a standardized five-row chart, so mapping coverage is the only thing
    left that can stand between it and published guidance."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    vendor = fx.create_vendor(
        api, name="Coverage Clothing", brand_code="COVR", correction_budget_cents=10000
    )
    item = fx.list_item(
        api,
        fx.create_item(
            api,
            vendor["id"],
            sku="COVR-TEE-01",
            category_code="TOPS",
            brand_size_system="US_ALPHA",
            unit_price_cents=2295,
        )["id"],
    )
    spec = fx.create_spec(
        api,
        item["id"],
        vendor["id"],
        size_system="US_ALPHA",
        base_size_label="M",
        fabric_stretch_class="RIGID",
        size_points=EQUALITY_FIVE_SIZE_POINTS,
        grade_rules=CHEST_GRADE_RULES,
    )
    fx.submit_spec(api, spec["id"], vendor["id"])
    fx.verify_spec(api, spec["id"])
    chart = fx.setup_standardized_chart(
        api,
        chart_code="STD-TOPS-CV",
        size_system="US_ALPHA",
        category_code="TOPS",
        rows=FIVE_ROW_TOPS_CHART,
    )
    fx.enhance_pdp(
        api,
        item["id"],
        model_measurements_published=True,
        detail_image_count=3,
        model_height_cm=178,
        model_worn_size_label="M",
    )
    return {"vendor": vendor, "item": item, "spec": spec, "chart": chart}


def test_three_of_five_pairs_leave_coverage_short_of_the_minimum(api):
    """PRD §3.3: "`coverage_bp` is `mapped_row_count` multiplied by 10,000, divided by
    `spec_size_point_count`, with any fraction discarded — and it is 0 when
    `spec_size_point_count` is 0."  Three accepted pairs against a five-point size run
    give 6,000 basis points, and the two labels no pair claimed are listed in the
    specification's own ascending order.

    Design: Difficulty/boundary_precision_check/coverage_exactly_at_minimum_publishes_guidance
    """
    built = _build_item_awaiting_a_mapping(api)

    mapping = fx.create_mapping(
        api,
        built["item"]["id"],
        built["chart"]["id"],
        size_label_pairs=THREE_OF_FIVE_PAIRS,
    )

    assert mapping["mapped_row_count"] == 3
    assert mapping["spec_size_point_count"] == 5
    assert mapping["coverage_bp"] == 6000
    assert mapping["unmapped_size_labels"] == ["XS", "XL"]

    item = fx.read_item(api, built["item"]["id"])
    assert item["fit_readiness"] == "CHART_MAPPED"


def test_publishing_is_refused_while_coverage_sits_below_eighty_percent(api):
    """PRD §3.4: "That mapping's `coverage_bp` must be at least 8,000 — eighty percent
    of the specification's size run must be mapped — otherwise
    `ERR_MAPPING_COVERAGE_INSUFFICIENT`."  A sixty-percent mapping is refused with
    HTTP 422, and the refusal leaves the readiness axis parked at chart-mapped so the
    analyst can widen the mapping and try again.

    Design: Difficulty/boundary_precision_check/coverage_exactly_at_minimum_publishes_guidance
    """
    built = _build_item_awaiting_a_mapping(api)
    fx.create_mapping(
        api,
        built["item"]["id"],
        built["chart"]["id"],
        size_label_pairs=THREE_OF_FIVE_PAIRS,
    )

    response = api.publish_guidance(built["item"]["id"], make_fit_analyst_headers())
    validate_error(response, ApiErrorId.ERR_MAPPING_COVERAGE_INSUFFICIENT.value, 422)

    item = fx.read_item(api, built["item"]["id"])
    assert item["fit_readiness"] == "CHART_MAPPED"


def test_a_fourth_pair_supersedes_the_narrow_mapping_and_reaches_the_minimum(api):
    """PRD §3.3: "Any prior `ACTIVE` mapping of that item moves to `SUPERSEDED` with
    `superseded_reason` `NEW_MAPPING`."  Remapping the same chart with a fourth pair
    retires the sixty-percent attempt rather than competing with it, and the surviving
    mapping reads exactly 8,000 basis points.

    Design: Difficulty/boundary_precision_check/coverage_exactly_at_minimum_publishes_guidance
    """
    built = _build_item_awaiting_a_mapping(api)
    narrow = fx.create_mapping(
        api,
        built["item"]["id"],
        built["chart"]["id"],
        size_label_pairs=THREE_OF_FIVE_PAIRS,
    )

    wide = fx.create_mapping(
        api,
        built["item"]["id"],
        built["chart"]["id"],
        size_label_pairs=FOUR_OF_FIVE_PAIRS,
    )

    assert wide["status"] == "ACTIVE"
    assert wide["mapped_row_count"] == 4
    assert wide["coverage_bp"] == 8000
    assert wide["unmapped_size_labels"] == ["XS"]

    superseded = fx.read_mapping(api, narrow["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["superseded_reason"] == "NEW_MAPPING"


def test_coverage_of_exactly_eight_thousand_publishes_guidance(api):
    """PRD §2.9: "The item's active mapping has `coverage_bp` of at least 8,000,
    otherwise `ERR_MAPPING_COVERAGE_INSUFFICIENT` (422)."  At least 8,000 includes
    8,000, so the four-pair mapping that was one pair away from refusal publishes,
    carrying the readiness axis to guidance-ready while the storefront axis stays
    listed.

    Design: Difficulty/boundary_precision_check/coverage_exactly_at_minimum_publishes_guidance
    """
    built = _build_item_awaiting_a_mapping(api)
    mapping = fx.create_mapping(
        api,
        built["item"]["id"],
        built["chart"]["id"],
        size_label_pairs=FOUR_OF_FIVE_PAIRS,
    )
    assert mapping["coverage_bp"] == 8000

    item = validate_success(
        api.publish_guidance(built["item"]["id"], make_fit_analyst_headers())
    )

    assert item["fit_readiness"] == "GUIDANCE_READY"
    assert item["listing_status"] == "LISTED"


def test_the_narrow_mapping_still_refuses_when_it_is_the_active_one(api):
    """PRD §3.3: "Only one mapping per item is `ACTIVE` at a time."  Coverage is read
    from whichever mapping is active, so re-narrowing an item that had already reached
    the minimum drops it back to chart-mapped and returns the coverage refusal, which
    is what makes the eight-thousand admission a genuine boundary rather than a
    one-way ratchet.

    Design: Difficulty/boundary_precision_check/coverage_exactly_at_minimum_publishes_guidance
    """
    built = _build_item_awaiting_a_mapping(api)
    fx.create_mapping(
        api,
        built["item"]["id"],
        built["chart"]["id"],
        size_label_pairs=FOUR_OF_FIVE_PAIRS,
    )
    fx.publish_guidance(api, built["item"]["id"])

    narrow = fx.create_mapping(
        api,
        built["item"]["id"],
        built["chart"]["id"],
        size_label_pairs=THREE_OF_FIVE_PAIRS,
    )
    assert narrow["status"] == "ACTIVE"
    assert narrow["coverage_bp"] == 6000

    item = fx.read_item(api, built["item"]["id"])
    assert item["fit_readiness"] == "CHART_MAPPED"

    response = api.publish_guidance(built["item"]["id"], make_fit_analyst_headers())
    validate_error(response, ApiErrorId.ERR_MAPPING_COVERAGE_INSUFFICIENT.value, 422)
