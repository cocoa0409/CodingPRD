"""Lifecycles that are not straight lines.

A measurement specification can be sent back and re-enter the state it already
left, so its lifecycle is a cycle.  A catalog item carries two state axes on the
same row that advance on different triggers, so its lifecycle is parallel.  Both
shapes are observable only by watching a sequence of responses rather than a
single one.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ApiClient,
    chart_row,
    expected_tolerance_mm,
    grade_rule,
    is_iso8601_timestamp,
    make_fit_analyst_headers,
    make_vendor_user_headers,
    size_label_pair,
    size_point,
    validate_success,
)
from test_helpers import fixtures as fx  # noqa: E402

# A five-size chest run graded by 40 millimetres.  The M-to-L step is 46, which is
# 6 millimetres away from the declared increment against an enforced tolerance of
# 5, so verification records exactly one violation and names M as the lower size.
VIOLATING_FIVE_SIZE_POINTS = [
    size_point("XS", 0, 800, 720, 840, 700),
    size_point("S", 1, 840, 760, 880, 710),
    size_point("M", 2, 880, 800, 920, 720),
    size_point("L", 3, 926, 845, 965, 730),
    size_point("XL", 4, 965, 885, 1005, 740),
]

# The same run with the L chest one millimetre lower, so the M-to-L step deviates
# by exactly the enforced tolerance and therefore passes.
CORRECTED_FIVE_SIZE_POINTS = [
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

FOUR_OF_FIVE_PAIRS = [
    size_label_pair("S", "S"),
    size_label_pair("M", "M"),
    size_label_pair("L", "L"),
    size_label_pair("XL", "XL"),
]


def _build_correction_requested_spec(api: ApiClient) -> dict:
    """A listed item whose submitted specification has been verified once and sent
    back for correction on its chest grade."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    vendor = fx.create_vendor(
        api, name="Loopback Mills", brand_code="LOOP", correction_budget_cents=10000
    )
    item = fx.list_item(
        api,
        fx.create_item(
            api,
            vendor["id"],
            sku="LOOP-TEE-01",
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
        size_points=VIOLATING_FIVE_SIZE_POINTS,
        grade_rules=CHEST_GRADE_RULES,
    )
    fx.submit_spec(api, spec["id"], vendor["id"])
    return {"vendor": vendor, "item": item, "spec": spec}


def test_a_tolerance_violation_sends_the_submitted_specification_back_for_correction(api):
    """PRD §3.2: "`violation_count` is the number of violations found across all
    points."  Only the M-to-L chest step breaks the five-millimetre enforced
    tolerance, so the count is 1, the first-violation fields name that pair's lower
    size, and the specification leaves `SUBMITTED` for `CORRECTION_REQUESTED` while
    its revision round is still 0.

    Design: Difficulty/non_linear_state_machine/spec_correction_loop_returns_to_submitted
    """
    built = _build_correction_requested_spec(api)

    spec = validate_success(
        api.verify_measurement_spec(built["spec"]["id"], make_fit_analyst_headers())
    )

    assert spec["status"] == "CORRECTION_REQUESTED"
    assert spec["violation_count"] == 1
    assert spec["first_violation_point"] == "CHEST"
    assert spec["first_violation_from_size_label"] == "M"
    assert spec["revision_round"] == 0
    assert spec["correction_reason"] == "GRADE_TOLERANCE_VIOLATION"
    assert spec["tolerance_applied_mm"] == [
        {
            "measurement_point": "CHEST",
            "tolerance_mm": expected_tolerance_mm(40, 1250, 3, "CHEST", "RIGID"),
        }
    ]


def test_resubmission_carries_the_specification_back_into_submitted(api):
    """PRD §3.2: "`revision_round` then increases by 1, `correction_reason` is
    cleared to null, and the specification returns to `SUBMITTED` for another
    verification pass."  The state the specification already left is the state it
    re-enters, which is what makes this lifecycle a cycle rather than a pipeline.

    Design: Difficulty/non_linear_state_machine/spec_correction_loop_returns_to_submitted
    """
    built = _build_correction_requested_spec(api)
    fx.verify_spec(api, built["spec"]["id"])

    spec = validate_success(
        api.resubmit_measurement_spec(
            built["spec"]["id"],
            {"size_points": CORRECTED_FIVE_SIZE_POINTS},
            make_vendor_user_headers(built["vendor"]["id"]),
        )
    )

    assert spec["status"] == "SUBMITTED"
    assert spec["revision_round"] == 1
    assert spec["correction_reason"] is None


def test_the_second_pass_verifies_and_records_the_tolerance_it_enforced(api):
    """PRD §3.2: "The resolved value is appended to `tolerance_applied_mm` as an
    object pairing that `measurement_point` with its `tolerance_mm`, so the stored
    array records exactly which tolerance was enforced at each point on the last
    verification run."  The corrected M-to-L step deviates by exactly five
    millimetres, which passes, so the second pass clears both first-violation fields
    and stamps the verifying analyst and the logical clock.

    Design: Difficulty/non_linear_state_machine/spec_correction_loop_returns_to_submitted
    """
    built = _build_correction_requested_spec(api)
    fx.verify_spec(api, built["spec"]["id"])
    fx.resubmit_spec(
        api,
        built["spec"]["id"],
        built["vendor"]["id"],
        size_points=CORRECTED_FIVE_SIZE_POINTS,
    )

    spec = fx.verify_spec(api, built["spec"]["id"])

    assert spec["status"] == "VERIFIED"
    assert spec["violation_count"] == 0
    assert spec["first_violation_point"] is None
    assert spec["first_violation_from_size_label"] is None
    assert spec["revision_round"] == 1
    assert spec["tolerance_applied_mm"] == [
        {"measurement_point": "CHEST", "tolerance_mm": 5}
    ]
    assert spec["verified_by_user_id"] == "analyst-7"
    assert is_iso8601_timestamp(spec["verified_at"])
    assert spec["verified_at"].startswith("2026-06-01T00:00:00")


def test_the_round_the_loop_cost_stays_debited_against_the_brand(api):
    """PRD §2.11: "`reliability_score_bp` starts at 10,000 basis points — a perfect
    record — and is recomputed as 10,000 less 500 basis points for each non-reversed
    quality chargeback counted in `quality_chargeback_count`, less 300 basis points
    for each correction round counted in `correction_round_count`, with the result
    floored at 0 so the score can never go negative."  One round through the loop
    leaves 9,700 basis points and a 2,500-cent debit that reaching `VERIFIED` does
    not refund, while the score is still high enough to keep the brand active.

    Design: Difficulty/non_linear_state_machine/spec_correction_loop_returns_to_submitted
    """
    built = _build_correction_requested_spec(api)
    fx.verify_spec(api, built["spec"]["id"])
    fx.resubmit_spec(
        api,
        built["spec"]["id"],
        built["vendor"]["id"],
        size_points=CORRECTED_FIVE_SIZE_POINTS,
    )
    fx.verify_spec(api, built["spec"]["id"])

    vendor = fx.read_vendor(api, built["vendor"]["id"])
    assert vendor["correction_round_count"] == 1
    assert vendor["correction_spend_cents"] == 2500
    assert vendor["reliability_score_bp"] == 9700
    assert vendor["status"] == "ACTIVE"


def _build_item_with_spec_and_chart(api: ApiClient) -> dict:
    """A draft item whose clean five-point specification is submitted and whose
    standardized five-row chart is waiting, so both axes can then be advanced one
    trigger at a time."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    vendor = fx.create_vendor(
        api, name="Axis Apparel", brand_code="AXIS", correction_budget_cents=10000
    )
    item = fx.create_item(
        api,
        vendor["id"],
        sku="AXIS-TEE-01",
        category_code="TOPS",
        brand_size_system="US_ALPHA",
        unit_price_cents=2295,
    )
    spec = fx.create_spec(
        api,
        item["id"],
        vendor["id"],
        size_system="US_ALPHA",
        base_size_label="M",
        fabric_stretch_class="RIGID",
        size_points=CORRECTED_FIVE_SIZE_POINTS,
        grade_rules=CHEST_GRADE_RULES,
    )
    fx.submit_spec(api, spec["id"], vendor["id"])
    chart = fx.setup_standardized_chart(
        api,
        chart_code="STD-TOPS-AX",
        size_system="US_ALPHA",
        category_code="TOPS",
        rows=FIVE_ROW_TOPS_CHART,
    )
    return {"vendor": vendor, "item": item, "spec": spec, "chart": chart}


def test_listing_and_verifying_both_leave_the_readiness_axis_untouched(api):
    """PRD §3.1: "Putting an item on the storefront is a `MerchOpsAdmin` action that
    advances `listing_status` from `DRAFT` to `LISTED` and increments the item's
    `version` by 1; the readiness axis is deliberately untouched, because listing an
    item and being ready to give fit advice about it are separate achievements."  A
    fresh item opens at `DRAFT` and `UNVERIFIED`; listing it and then verifying its
    specification both leave the readiness axis exactly where it stood.

    Design: Difficulty/non_linear_state_machine/item_listing_and_fit_readiness_axes_advance_independently
    """
    built = _build_item_with_spec_and_chart(api)

    assert built["item"]["listing_status"] == "DRAFT"
    assert built["item"]["fit_readiness"] == "UNVERIFIED"

    listed = fx.list_item(api, built["item"]["id"])
    assert listed["listing_status"] == "LISTED"
    assert listed["fit_readiness"] == "UNVERIFIED"

    fx.verify_spec(api, built["spec"]["id"])
    after_verify = fx.read_item(api, built["item"]["id"])
    assert after_verify["listing_status"] == "LISTED"
    assert after_verify["fit_readiness"] == "UNVERIFIED"


def test_mapping_advances_readiness_and_leaves_the_storefront_axis_alone(api):
    """PRD §3.3: "In every case the item's `version` increments by 1 and its
    `listing_status` is untouched."  Pairing four of the specification's five labels
    onto the standardized chart carries the readiness axis from `UNVERIFIED` to
    `CHART_MAPPED` at eighty percent coverage while the item stays listed.

    Design: Difficulty/non_linear_state_machine/item_listing_and_fit_readiness_axes_advance_independently
    """
    built = _build_item_with_spec_and_chart(api)
    fx.list_item(api, built["item"]["id"])
    fx.verify_spec(api, built["spec"]["id"])

    mapping = fx.create_mapping(
        api,
        built["item"]["id"],
        built["chart"]["id"],
        size_label_pairs=FOUR_OF_FIVE_PAIRS,
    )
    assert mapping["status"] == "ACTIVE"
    assert mapping["coverage_bp"] == 8000

    item = fx.read_item(api, built["item"]["id"])
    assert item["listing_status"] == "LISTED"
    assert item["fit_readiness"] == "CHART_MAPPED"


def test_publishing_guidance_completes_the_readiness_axis_on_a_still_listed_item(api):
    """PRD §3.4: "Publishing guidance is a `FitAnalyst` action and it advances the
    readiness axis from `CHART_MAPPED` to `GUIDANCE_READY`, after which fit
    recommendations become servable for the item."  The item passes through
    (`LISTED`, `UNVERIFIED`), (`LISTED`, `CHART_MAPPED`) and (`LISTED`,
    `GUIDANCE_READY`) without either axis ever gating the other, and its
    chronic-return classification is untouched throughout.

    Design: Difficulty/non_linear_state_machine/item_listing_and_fit_readiness_axes_advance_independently
    """
    built = _build_item_with_spec_and_chart(api)
    fx.list_item(api, built["item"]["id"])
    fx.verify_spec(api, built["spec"]["id"])
    fx.create_mapping(
        api,
        built["item"]["id"],
        built["chart"]["id"],
        size_label_pairs=FOUR_OF_FIVE_PAIRS,
    )
    fx.enhance_pdp(
        api,
        built["item"]["id"],
        model_measurements_published=True,
        detail_image_count=3,
        model_height_cm=178,
        model_worn_size_label="M",
    )

    item = fx.publish_guidance(api, built["item"]["id"])

    assert item["listing_status"] == "LISTED"
    assert item["fit_readiness"] == "GUIDANCE_READY"
    assert item["fit_watch_state"] == "NORMAL"
