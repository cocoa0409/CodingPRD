"""Computed reads that offer two calculation variants over one body of data.

Both the fit recommendation and the lever savings report recalculate on demand and
echo which variant ran, so the divergence between them is observable from the
response rather than inferred.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ApiClient,
    assert_net_savings_consistent,
    chart_row,
    grade_rule,
    make_customer_headers,
    make_fit_analyst_headers,
    size_label_pair,
    size_point,
    validate_success,
)
from test_helpers import fixtures as fx  # noqa: E402

# A five-size run whose chest steps are 40, 40, 45 and 40 millimetres against a
# declared 40-millimetre increment and a five-millimetre enforced tolerance.
FIVE_SIZE_POINTS = [
    size_point("XS", 0, 800, 720, 840, 700),
    size_point("S", 1, 840, 760, 880, 710),
    size_point("M", 2, 880, 800, 920, 720),
    size_point("L", 3, 925, 845, 965, 730),
    size_point("XL", 4, 965, 885, 1005, 740),
]

FIVE_CHART_ROWS = [
    chart_row("XS", 0, 780, 819, 700, 739, "XS", "0", "32", "4"),
    chart_row("S", 1, 820, 859, 740, 779, "S", "2", "34", "6"),
    chart_row("M", 2, 860, 899, 780, 819, "M", "4", "36", "8"),
    chart_row("L", 3, 900, 944, 820, 864, "L", "6", "38", "10"),
    chart_row("XL", 4, 945, 984, 865, 904, "XL", "8", "40", "12"),
]

FOUR_PAIRS = [
    size_label_pair("S", "S"),
    size_label_pair("M", "M"),
    size_label_pair("L", "L"),
    size_label_pair("XL", "XL"),
]


def _build_personal_history_scenario(api: ApiClient) -> dict:
    """A GUIDANCE_READY target item that carries no fit feedback of its own, plus a
    shopper whose personal pool holds three contributions in the same category:
    two active feedback rows and one refunded fit return."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    vendor = fx.create_vendor(
        api,
        name="Northwind Apparel",
        brand_code="NRTH",
        correction_budget_cents=10000,
    )
    target = fx.list_item(
        api, fx.create_item(api, vendor["id"], sku="NRTH-TEE-01")["id"]
    )
    item_a = fx.list_item(
        api, fx.create_item(api, vendor["id"], sku="NRTH-TEE-AUX-A")["id"]
    )
    item_b = fx.list_item(
        api, fx.create_item(api, vendor["id"], sku="NRTH-TEE-AUX-B")["id"]
    )

    spec = fx.create_spec(
        api,
        target["id"],
        vendor["id"],
        base_size_label="M",
        size_points=FIVE_SIZE_POINTS,
        grade_rules=[grade_rule("CHEST", 40, 1250, 3)],
    )
    fx.submit_spec(api, spec["id"], vendor["id"])
    fx.verify_spec(api, spec["id"])

    chart = fx.setup_standardized_chart(
        api, chart_code="STD-TOPS-A1", rows=FIVE_CHART_ROWS
    )
    mapping = fx.create_mapping(
        api, target["id"], chart["id"], size_label_pairs=FOUR_PAIRS
    )
    fx.enhance_pdp(api, target["id"], detail_image_count=3)
    target = fx.publish_guidance(api, target["id"])

    customer = fx.create_customer(api, email="shopper-r1@example.com")
    fx.create_policy(api)
    fx.create_order_line(
        api,
        customer["id"],
        item_a["id"],
        size_label="M",
        delivered_at="2026-05-20T00:00:00Z",
    )
    line_b = fx.create_order_line(
        api,
        customer["id"],
        item_b["id"],
        size_label="S",
        delivered_at="2026-05-10T00:00:00Z",
    )
    case_b = fx.open_case(
        api, line_b["id"], customer["id"], requested_reason_code="FIT_TOO_SMALL"
    )
    fx.classify_case(api, case_b["id"], "FIT_TOO_SMALL")
    fx.resolve_case(api, case_b["id"], "RESELLABLE_A")

    feedback_a = fx.post_feedback(
        api,
        item_a["id"],
        customer["id"],
        purchased_size_label="M",
        fit_verdict="TOO_SMALL",
    )
    feedback_b = fx.post_feedback(
        api,
        item_b["id"],
        customer["id"],
        purchased_size_label="S",
        fit_verdict="SLIGHTLY_SMALL",
    )
    return {
        "target": target,
        "mapping": mapping,
        "customer": customer,
        "feedback_a": feedback_a,
        "feedback_b": feedback_b,
    }


def test_history_weighted_recommendation_walks_up_one_size_from_a_personal_anchor(api):
    """PRD §3.6: "The confidence cap is the smaller of 9,500 and the quantity
    4,500 plus 1,000 multiplied by `sample_count`." The shopper's pool holds three
    contributions, so the cap is 7,500; against a coverage of 8,000 basis points
    the confidence is 6,000, which is not strictly below 6,000 and therefore
    emits a label.  The anchor is the chart row paired with the size on the
    shopper's most recent same-category line, and a weighted offset of 83
    hundredths of a step shifts it up by one whole size.

    Design: Difficulty/dual_variant_calc/fit_recommendation_history_vs_population_divergence
    """
    built = _build_personal_history_scenario(api)

    response = api.get_fit_recommendation(
        built["target"]["id"],
        make_customer_headers(built["customer"]["id"]),
        {"customer_profile_id": built["customer"]["id"]},
    )
    data = validate_success(response)

    assert data["variant_applied"] == "history_weighted"
    assert data["sample_count"] == 3
    assert data["anchor_index"] == 2
    assert data["recommended_index"] == 3
    assert data["recommended_size_label"] == "L"
    assert data["confidence_bp"] == 6000
    assert data["suppressed"] is False
    assert data["coverage_bp"] == 8000


def test_population_fallback_recommendation_is_suppressed_on_an_empty_item_pool(api):
    """PRD §3.6: "The confidence cap is the smaller of 8,000 and the quantity
    2,000 plus 500 multiplied by `sample_count`." Read without a
    `customer_profile_id`, the same stored data is scored against this item's own
    feedback pool, which is empty: the cap is 2,000, the confidence falls to
    1,600, and the result is suppressed with a null label while the anchor stays
    at the chart's median row.

    Design: Difficulty/dual_variant_calc/fit_recommendation_history_vs_population_divergence
    """
    built = _build_personal_history_scenario(api)

    response = api.get_fit_recommendation(
        built["target"]["id"], make_fit_analyst_headers()
    )
    data = validate_success(response)

    assert data["variant_applied"] == "population_fallback"
    assert data["sample_count"] == 0
    assert data["anchor_index"] == 2
    assert data["recommended_index"] == 2
    assert data["confidence_bp"] == 1600
    assert data["suppressed"] is True
    assert data["recommended_size_label"] is None


def test_purchaser_feedback_weight_and_partial_coverage_feed_both_variants(api):
    """PRD §3.5: "`signal_weight` is 200 when the reviewer actually owns the item
    — that is, when the reviewer has an order line on this item whose `status` is
    `DELIVERED`, `RETURN_IN_PROGRESS`, `RETURNED`, or `KEPT` — and 100 otherwise,
    so verified purchasers count double." Both feedback rows come from a verified
    purchaser, and the four-pair mapping over a five-point specification leaves
    exactly one label uncovered, which is the coverage figure both variants scale
    their confidence by.

    Design: Difficulty/dual_variant_calc/fit_recommendation_history_vs_population_divergence
    """
    built = _build_personal_history_scenario(api)

    assert built["feedback_a"]["signal_weight"] == 200
    assert built["feedback_b"]["signal_weight"] == 200

    mapping = fx.read_mapping(api, built["mapping"]["id"])
    assert mapping["coverage_bp"] == 8000
    assert mapping["unmapped_size_labels"] == ["XS"]


def _build_two_deployment_cohort(api: ApiClient) -> dict:
    """One lever with two measured deployments on two items whose snapshotted
    baselines differ: item A at 5,000 basis points improving to 0, item B at
    2,500 improving to 1,250."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    vendor = fx.create_vendor(
        api, name="Cohort Mills", brand_code="CHRT", correction_budget_cents=10000
    )
    item_a = fx.list_item(
        api,
        fx.create_item(api, vendor["id"], sku="CHRT-A", unit_price_cents=3000)["id"],
    )
    item_b = fx.list_item(
        api,
        fx.create_item(api, vendor["id"], sku="CHRT-B", unit_price_cents=3000)["id"],
    )
    fx.create_policy(api)
    customer = fx.create_customer(api, email="cohort-shopper@example.com")

    def line(item_id, quantity, delivered_at):
        return fx.create_order_line(
            api,
            customer["id"],
            item_id,
            quantity=quantity,
            unit_price_cents=3000,
            delivered_at=delivered_at,
        )

    def refunded_fit_return(order_line_id):
        case = fx.open_case(
            api,
            order_line_id,
            customer["id"],
            requested_reason_code="FIT_TOO_SMALL",
        )
        fx.classify_case(api, case["id"], "FIT_TOO_SMALL")
        return fx.resolve_case(api, case["id"], "RESELLABLE_A")

    a_pre = line(item_a["id"], 1, "2026-05-10T00:00:00Z")
    line(item_a["id"], 1, "2026-05-12T00:00:00Z")
    b_pre = line(item_b["id"], 3, "2026-05-10T00:00:00Z")
    line(item_b["id"], 1, "2026-05-12T00:00:00Z")
    refunded_fit_return(a_pre["id"])
    refunded_fit_return(b_pre["id"])

    intervention = fx.create_intervention(
        api,
        name="PDP model measurements rollout",
        lever="PDP_MODEL_MEASUREMENTS",
        unit_cost_cents=1500,
    )
    d1 = fx.create_deployment(
        api,
        intervention["id"],
        item_a["id"],
        window_start="2026-07-01T00:00:00Z",
        window_end="2026-08-01T00:00:00Z",
        spend_cents=1500,
    )
    d2 = fx.create_deployment(
        api,
        intervention["id"],
        item_b["id"],
        window_start="2026-07-10T00:00:00Z",
        window_end="2026-08-01T00:00:00Z",
        spend_cents=1500,
    )

    fx.set_clock(api, "2026-07-02T00:00:00Z")
    fx.run_ops_run(api)
    fx.set_clock(api, "2026-07-11T00:00:00Z")
    fx.run_ops_run(api)

    line(item_a["id"], 1, "2026-07-05T00:00:00Z")
    line(item_a["id"], 1, "2026-07-06T00:00:00Z")

    fx.set_clock(api, "2026-07-20T00:00:00Z")
    b_win = line(item_b["id"], 4, "2026-07-15T00:00:00Z")
    line(item_b["id"], 4, "2026-07-16T00:00:00Z")
    refunded_fit_return(b_win["id"])

    fx.set_clock(api, "2026-08-02T00:00:00Z")
    fx.run_ops_run(api)
    fx.run_ops_run(api)

    return {
        "intervention": intervention,
        "deployment_a": d1,
        "deployment_b": d2,
        "item_a": item_a,
        "item_b": item_b,
    }


def test_each_deployment_is_measured_against_its_own_snapshotted_baseline(api):
    """PRD §3.9: "`avoided_return_count` is that improvement multiplied by
    `window_units_count`, divided by 10,000, with any fraction discarded — whole
    avoided returns only." The two deployments start from different snapshotted
    baselines and see different in-window volumes, yet each is credited with
    exactly one avoided return and the same 3,200-cent valuation for a `TOPS`
    item.

    Design: Difficulty/dual_variant_calc/intervention_savings_attributed_vs_cohort_chronological_divergence
    """
    built = _build_two_deployment_cohort(api)

    first = fx.read_deployment(api, built["deployment_a"]["id"])
    assert first["status"] == "MEASURED"
    assert first["baseline_units_count"] == 2
    assert first["baseline_return_rate_bp"] == 5000
    assert first["window_units_count"] == 2
    assert first["measured_return_rate_bp"] == 0
    assert first["avoided_return_count"] == 1
    assert first["attributed_savings_cents"] == 3200

    second = fx.read_deployment(api, built["deployment_b"]["id"])
    assert second["status"] == "MEASURED"
    assert second["baseline_units_count"] == 4
    assert second["baseline_return_rate_bp"] == 2500
    assert second["window_units_count"] == 8
    assert second["measured_return_rate_bp"] == 1250
    assert second["avoided_return_count"] == 1
    assert second["attributed_savings_cents"] == 3200


def test_deployment_attributed_report_sums_both_credits_and_matches_the_stored_lever(api):
    """PRD §3.9: "Gross savings is the plain sum of each `MEASURED` deployment's
    own `attributed_savings_cents`." Two additive credits of 3,200 cents against
    3,000 cents of recognized spend leave the lever funded, and this is the
    variant whose numbers the lever row itself persists.

    Design: Difficulty/dual_variant_calc/intervention_savings_attributed_vs_cohort_chronological_divergence
    """
    built = _build_two_deployment_cohort(api)

    report = validate_success(
        api.get_savings_report(built["intervention"]["id"], make_fit_analyst_headers())
    )
    assert report["variant_applied"] == "deployment_attributed"
    assert report["gross_savings_cents"] == 6400
    assert report["spend_cents"] == 3000
    assert report["net_savings_cents"] == 3400
    assert report["measured_deployment_count"] == 2
    assert report["avoided_return_count"] == 2
    assert report["funding_posture"] == "FUNDED"
    assert_net_savings_consistent(report)

    lever = fx.read_intervention(api, built["intervention"]["id"])
    assert lever["gross_savings_cents"] == 6400
    assert lever["net_savings_cents"] == 3400


def test_cohort_chronological_report_credits_only_gains_beyond_the_running_baseline(api):
    """PRD §3.9: "The running baseline begins as the `baseline_return_rate_bp` of
    the first deployment in that order." Replayed in window order the first
    deployment drives the cohort rate to 0, so the second deployment's own
    improvement from 2,500 to 1,250 earns nothing and gross savings fall to a
    single credit over byte-identical stored data.

    Design: Difficulty/dual_variant_calc/intervention_savings_attributed_vs_cohort_chronological_divergence
    """
    built = _build_two_deployment_cohort(api)

    report = validate_success(
        api.get_savings_report(
            built["intervention"]["id"],
            make_fit_analyst_headers(),
            {"variant": "cohort_chronological"},
        )
    )
    assert report["variant_applied"] == "cohort_chronological"
    assert report["gross_savings_cents"] == 3200
    assert report["spend_cents"] == 3000
    assert report["net_savings_cents"] == 200
    assert report["avoided_return_count"] == 1
    assert report["funding_posture"] == "FUNDED"


def test_a_measured_window_leaves_each_item_watch_state_derived_from_its_own_volume(api):
    """PRD §3.8: "`fit_watch_state` follows from the score and the raw fit count
    together: `CHRONIC` when the score is at least 2,500 basis points **and**
    `fit_return_count` is at least 2; otherwise `WATCH` when the score is at
    least 1,500 basis points **and** `fit_return_count` is at least 1; otherwise
    `NORMAL`." One fit return over four units scores 1,875 and reaches watch,
    while two fit returns over twelve units score only 1,249 and stay normal.

    Design: Difficulty/dual_variant_calc/intervention_savings_attributed_vs_cohort_chronological_divergence
    """
    built = _build_two_deployment_cohort(api)

    item_a = fx.read_item(api, built["item_a"]["id"])
    assert item_a["fit_return_count"] == 1
    assert item_a["fit_return_rate_bp"] == 2500
    assert item_a["chronic_return_score_bp"] == 1875
    assert item_a["fit_watch_state"] == "WATCH"

    item_b = fx.read_item(api, built["item_b"]["id"])
    assert item_b["fit_return_count"] == 2
    assert item_b["fit_return_rate_bp"] == 1666
    assert item_b["chronic_return_score_bp"] == 1249
    assert item_b["fit_watch_state"] == "NORMAL"
