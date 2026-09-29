"""Single requests whose consequences run four entities deep.

Cascades here are immediate and synchronous, so the whole chain is already
committed by the time the triggering response comes back.  Two chains are
exercised: one that starts at a return resolution and reaches the vendor's
standing, and one that starts at chart retirement and reaches a lever's funding.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ApiClient,
    chart_row,
    grade_rule,
    make_returns_auditor_headers,
    resolve_return_case_payload,
    size_label_pair,
    size_point,
    validate_success,
)
from test_helpers import fixtures as fx  # noqa: E402

CLEAN_FIVE_SIZE_POINTS = [
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


def _build_guidance_ready_item(
    api: ApiClient,
    vendor_name: str,
    brand_code: str,
    sku: str,
    chart_code: str,
    correction_budget_cents: int,
    unit_price_cents: int,
) -> dict:
    """A listed TOPS item carried all the way to guidance-ready on a verified
    specification, a standardized chart and an active four-pair mapping."""
    vendor = fx.create_vendor(
        api,
        name=vendor_name,
        brand_code=brand_code,
        correction_budget_cents=correction_budget_cents,
    )
    item = fx.list_item(
        api,
        fx.create_item(
            api,
            vendor["id"],
            sku=sku,
            category_code="TOPS",
            brand_size_system="US_ALPHA",
            unit_price_cents=unit_price_cents,
        )["id"],
    )
    spec = fx.create_spec(
        api,
        item["id"],
        vendor["id"],
        size_system="US_ALPHA",
        base_size_label="M",
        fabric_stretch_class="RIGID",
        size_points=CLEAN_FIVE_SIZE_POINTS,
        grade_rules=CHEST_GRADE_RULES,
    )
    fx.submit_spec(api, spec["id"], vendor["id"])
    fx.verify_spec(api, spec["id"])
    chart = fx.setup_standardized_chart(
        api,
        chart_code=chart_code,
        size_system="US_ALPHA",
        category_code="TOPS",
        rows=FIVE_ROW_TOPS_CHART,
    )
    mapping = fx.create_mapping(
        api, item["id"], chart["id"], size_label_pairs=FOUR_OF_FIVE_PAIRS
    )
    fx.enhance_pdp(
        api,
        item["id"],
        model_measurements_published=True,
        detail_image_count=3,
        model_height_cm=178,
        model_worn_size_label="M",
    )
    item = fx.publish_guidance(api, item["id"])
    return {
        "vendor": vendor,
        "item": item,
        "spec": spec,
        "chart": chart,
        "mapping": mapping,
    }


def _build_item_one_return_short_of_chronic(api: ApiClient) -> dict:
    """A guidance-ready item on four delivered units that already carries one
    refunded fit return, so it sits at watch with a second fit case waiting in its
    review branch."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    built = _build_guidance_ready_item(
        api,
        vendor_name="Chronic Knitwear",
        brand_code="CHRN",
        sku="CHRN-TEE-01",
        chart_code="STD-TOPS-CH",
        correction_budget_cents=2000,
        unit_price_cents=3000,
    )
    fx.create_policy(
        api,
        category_code="TOPS",
        window_days=30,
        restocking_applies=True,
        non_refundable_shipping=False,
        effective_from="2026-01-01T00:00:00Z",
    )
    customer = fx.create_customer(api, email="shopper-r4a@example.com")
    lines = [
        fx.create_order_line(
            api,
            customer["id"],
            built["item"]["id"],
            size_label=label,
            quantity=1,
            unit_price_cents=3000,
            shipping_allocated_cents=0,
            delivered_at="2026-05-20T00:00:00Z",
        )
        for label in ("M", "M", "L", "L")
    ]

    first = fx.open_case(
        api, lines[0]["id"], customer["id"], requested_reason_code="FIT_TOO_SMALL"
    )
    fx.classify_case(api, first["id"], "FIT_TOO_SMALL")
    fx.resolve_case(api, first["id"], "RESELLABLE_A")

    second = fx.open_case(
        api, lines[1]["id"], customer["id"], requested_reason_code="FIT_TOO_SMALL"
    )
    second = fx.classify_case(api, second["id"], "FIT_TOO_SMALL")

    built["customer"] = customer
    built["order_lines"] = lines
    built["first_case"] = first
    built["second_case"] = second
    built["item"] = fx.read_item(api, built["item"]["id"])
    return built


def test_the_second_fit_return_lifts_the_chronic_score_past_the_flip_threshold(api):
    """PRD §3.8: "`chronic_return_score_bp` is then 7,500 multiplied by
    `fit_return_rate_bp`, plus 2,500 multiplied by `expectation_return_rate_bp`, all
    divided by 10,000, with any fraction discarded — a three-quarters weight on fit
    and a one-quarter weight on expectation."  One fit return over four units scores
    1,875 and only reaches watch; the second lifts the fit rate to 5,000 and the
    score to 3,750, which is the first hop of the chain.

    Design: Difficulty/transitive_cascade/chronic_flip_cascade_suspends_listing_reopens_spec_and_debits_vendor
    """
    built = _build_item_one_return_short_of_chronic(api)

    assert built["item"]["fit_watch_state"] == "WATCH"
    assert built["item"]["chronic_return_score_bp"] == 1875
    assert built["item"]["listing_status"] == "LISTED"
    assert built["item"]["fit_readiness"] == "GUIDANCE_READY"
    assert built["item"]["return_cost_accrued_cents"] == 1485

    case = validate_success(
        api.resolve_return_case(
            built["second_case"]["id"],
            resolve_return_case_payload("RESELLABLE_A"),
            make_returns_auditor_headers("auditor-2"),
        )
    )
    assert case["status"] == "RESOLVED_REFUNDED"
    assert case["refund_amount_cents"] == 3000
    assert case["total_cost_cents"] == 1485

    item = fx.read_item(api, built["item"]["id"])
    assert item["units_sold_count"] == 4
    assert item["fit_return_count"] == 2
    assert item["fit_return_rate_bp"] == 5000
    assert item["chronic_return_score_bp"] == 3750
    assert item["fit_watch_state"] == "CHRONIC"
    assert item["return_cost_accrued_cents"] == 2970


def test_the_chronic_flip_suspends_the_listing_and_resets_the_readiness_axis(api):
    """PRD §3.8: "An item whose `listing_status` is `LISTED` moves `LISTED →
    SUSPENDED`, incrementing its `version` by 1."  The flip is the one event that
    moves both item axes at once, so the same resolution that suspended the
    storefront listing also drops the readiness axis all the way back from
    guidance-ready.

    Design: Difficulty/transitive_cascade/chronic_flip_cascade_suspends_listing_reopens_spec_and_debits_vendor
    """
    built = _build_item_one_return_short_of_chronic(api)
    before_version = built["item"]["version"]

    fx.resolve_case(api, built["second_case"]["id"], "RESELLABLE_A")

    item = fx.read_item(api, built["item"]["id"])
    assert item["fit_watch_state"] == "CHRONIC"
    assert item["listing_status"] == "SUSPENDED"
    assert item["fit_readiness"] == "UNVERIFIED"
    assert item["version"] > before_version


def test_the_chronic_flip_reopens_the_items_verified_specification(api):
    """PRD §3.8: "And the item's single `VERIFIED` specification is reopened into
    `CORRECTION_REQUESTED` with `correction_reason` `CHRONIC_FIT_RETURNS`, which
    debits the vendor 2,500 cents, raises `correction_round_count` by 1, and
    re-derives `reliability_score_bp` and vendor `status`."  Nobody asked for this
    correction, so the revision round is still 0 and the reason distinguishes it from
    a tolerance failure.

    Design: Difficulty/transitive_cascade/chronic_flip_cascade_suspends_listing_reopens_spec_and_debits_vendor
    """
    built = _build_item_one_return_short_of_chronic(api)

    fx.resolve_case(api, built["second_case"]["id"], "RESELLABLE_A")

    spec = fx.read_spec(api, built["spec"]["id"])
    assert spec["status"] == "CORRECTION_REQUESTED"
    assert spec["correction_reason"] == "CHRONIC_FIT_RETURNS"
    assert spec["revision_round"] == 0


def test_the_reopened_specification_debits_the_brand_into_probation(api):
    """PRD §2.11: "From that score the vendor's `status` follows: `SUSPENDED` when
    the score is strictly below 5,000; otherwise `PROBATION` when the score is
    strictly below 7,000 **or** when `correction_spend_cents` strictly exceeds
    `correction_budget_cents`; otherwise `ACTIVE`."  One round costs 2,500 cents
    against a 2,000-cent funded budget, so the last hop of the chain moves the brand
    to probation on the overspend arm even though 9,700 basis points is comfortably
    above the reliability threshold.

    Design: Difficulty/transitive_cascade/chronic_flip_cascade_suspends_listing_reopens_spec_and_debits_vendor
    """
    built = _build_item_one_return_short_of_chronic(api)

    fx.resolve_case(api, built["second_case"]["id"], "RESELLABLE_A")

    vendor = fx.read_vendor(api, built["vendor"]["id"])
    assert vendor["correction_round_count"] == 1
    assert vendor["correction_spend_cents"] == 2500
    assert vendor["reliability_score_bp"] == 9700
    assert vendor["status"] == "PROBATION"

    customer = fx.read_customer(api, built["customer"]["id"])
    assert customer["return_case_count"] == 2
    assert customer["abuse_status"] == "CLEAR"
    assert customer["refunded_total_cents"] == 6000


def _build_active_badge_deployment_on_mapped_item(api: ApiClient) -> dict:
    """A guidance-ready item carrying a running fit-badge deployment, with the clock
    moved to the middle of the deployment's window so a mid-window closure has
    somewhere to rewrite the window end to."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    built = _build_guidance_ready_item(
        api,
        vendor_name="Retire Textiles",
        brand_code="RTIR",
        sku="RTIR-TEE-01",
        chart_code="STD-TOPS-RT",
        correction_budget_cents=10000,
        unit_price_cents=2295,
    )
    built["intervention"] = fx.create_intervention(
        api,
        name="Fit badge on PDP",
        lever="FIT_RECOMMENDATION_BADGE",
        unit_cost_cents=8000,
    )
    built["deployment"] = fx.create_deployment(
        api,
        built["intervention"]["id"],
        built["item"]["id"],
        window_start="2026-06-01T00:00:00Z",
        window_end="2026-09-01T00:00:00Z",
        spend_cents=8000,
    )
    built["activation_run"] = fx.run_ops_run(api)
    built["intervention_before"] = fx.read_intervention(api, built["intervention"]["id"])
    fx.set_clock(api, "2026-06-15T00:00:00Z")
    return built


def test_retiring_the_chart_supersedes_the_mapping_and_drops_only_readiness(api):
    """PRD §3.3: "Every size chart mapping of that chart whose `status` is `ACTIVE`
    moves to `SUPERSEDED` with `superseded_reason` `CHART_RETIRED`."  That
    supersession is the second hop and it drags the item's readiness axis back to
    unverified while the storefront axis stays exactly where it was.

    Design: Difficulty/transitive_cascade/chart_retirement_cascade_defunds_intervention
    """
    built = _build_active_badge_deployment_on_mapped_item(api)

    chart = fx.retire_chart(api, built["chart"]["id"], retire_reason_code="DATA_QUALITY")
    assert chart["status"] == "RETIRED"
    assert chart["retire_reason_code"] == "DATA_QUALITY"

    mapping = fx.read_mapping(api, built["mapping"]["id"])
    assert mapping["status"] == "SUPERSEDED"
    assert mapping["superseded_reason"] == "CHART_RETIRED"

    item = fx.read_item(api, built["item"]["id"])
    assert item["fit_readiness"] == "UNVERIFIED"
    assert item["listing_status"] == "LISTED"


def test_the_readiness_drop_terminates_the_running_badge_deployment(api):
    """PRD §3.3: "Each of those readiness drops in turn terminates that item's
    `ACTIVE` deployments whose intervention `lever` is `FIT_RECOMMENDATION_BADGE` or
    `SIZE_CHART_STANDARDIZATION`, with `terminated_reason_code`
    `MAPPING_SUPERSEDED` and `window_end` rewritten to the logical clock where the
    clock is earlier."  The deployment was activated by an earlier checkpoint and
    still had two and a half months to run, so its window end is pulled back to the
    instant the chart was retired.

    Design: Difficulty/transitive_cascade/chart_retirement_cascade_defunds_intervention
    """
    built = _build_active_badge_deployment_on_mapped_item(api)

    assert built["activation_run"]["deployments_activated"] == 1

    fx.retire_chart(api, built["chart"]["id"], retire_reason_code="DATA_QUALITY")

    deployment = fx.read_deployment(api, built["deployment"]["id"])
    assert deployment["status"] == "TERMINATED"
    assert deployment["terminated_reason_code"] == "MAPPING_SUPERSEDED"
    assert deployment["window_end"].startswith("2026-06-15T00:00:00")


def test_the_termination_recognizes_the_spend_and_defunds_the_lever(api):
    """PRD §3.9: "Closure is also the moment spend becomes real: the lever's
    `spend_cents` is the sum of `spend_cents` over its deployments whose `status` is
    `TERMINATED` or `MEASURED`, so a `SCHEDULED` or `ACTIVE` deployment contributes
    nothing to recognized spend, and closing one recognizes it and re-derives
    `net_savings_cents` and `funding_posture`."  While the deployment was merely
    running the lever recognized nothing and stayed funded; the closure recognizes
    8,000 cents against savings that were never measured, and the last hop of the
    chain defunds it.

    Design: Difficulty/transitive_cascade/chart_retirement_cascade_defunds_intervention
    """
    built = _build_active_badge_deployment_on_mapped_item(api)

    assert built["intervention_before"]["spend_cents"] == 0
    assert built["intervention_before"]["net_savings_cents"] == 0
    assert built["intervention_before"]["funding_posture"] == "FUNDED"

    fx.retire_chart(api, built["chart"]["id"], retire_reason_code="DATA_QUALITY")

    lever = fx.read_intervention(api, built["intervention"]["id"])
    assert lever["spend_cents"] == 8000
    assert lever["gross_savings_cents"] == 0
    assert lever["net_savings_cents"] == -8000
    assert lever["measured_deployment_count"] == 0
    assert lever["funding_posture"] == "DEFUNDED"
