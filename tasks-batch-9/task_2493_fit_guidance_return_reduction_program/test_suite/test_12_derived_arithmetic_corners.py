"""Derived numbers at the awkward end of their own formulas.

Every figure exercised here is computed rather than stored: a rate whose
denominator is zero, a return window whose arithmetic goes negative before it is
floored, a policy chosen out of two live candidates, a savings measurement split
across two half-open sets of order lines, and a cost ledger whose last posting is
negative.  Each scenario drives the arithmetic through public endpoints only and
reads the result back off the API.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ApiClient,
    create_return_case_payload,
    is_iso8601_timestamp,
    make_customer_headers,
    make_fit_analyst_headers,
    make_merch_ops_admin_headers,
    make_returns_auditor_headers,
    resolve_return_case_payload,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx  # noqa: E402

SCENARIO_START = "2026-06-01T00:00:00Z"

TOPS_THIRTY_DAY_POLICY = {
    "window_days": 30,
    "restocking_applies": True,
    "non_refundable_shipping": False,
    "effective_from": "2026-01-01T00:00:00Z",
}


def test_a_never_sold_item_scores_nothing_instead_of_dividing_by_zero(api):
    """PRD §3.8: "`fit_return_rate_bp` is `fit_return_count` multiplied by 10,000,
    divided by those units, with any fraction discarded, and is 0 when units are 0;
    `expectation_return_rate_bp` is the same shape over `expectation_return_count`."
    An item that has been put on the storefront but never purchased has no units to
    divide by, so both rates short-circuit to 0, the weighted score is 0, and the
    classification stays normal rather than tripping the watch branch.

    Design: Corner/calculations/chronic_score_with_zero_units_sold_stays_normal
    """
    built = fx.setup_listed_item(api, SCENARIO_START)

    item = validate_success(
        api.get_catalog_item(built["item"]["id"], make_fit_analyst_headers())
    )

    assert item["units_sold_count"] == 0
    assert item["fit_return_rate_bp"] == 0
    assert item["expectation_return_rate_bp"] == 0
    assert item["chronic_return_score_bp"] == 0
    assert item["fit_watch_state"] == "NORMAL"
    assert item["fit_return_count"] == 0
    assert item["expectation_return_count"] == 0
    assert item["total_return_count"] == 0
    assert item["listing_status"] == "LISTED"


def _build_shopper_with_two_change_of_mind_refunds(api: ApiClient) -> dict:
    """A shopper on a deliberately short ten-day window with three delivered lines,
    two of which have already been refunded as change-of-mind returns, so the
    shopper's standing has walked up two rungs of the abuse axis."""
    built = fx.setup_delivered_lines(
        api,
        3,
        SCENARIO_START,
        policy_overrides={
            "window_days": 10,
            "restocking_applies": True,
            "non_refundable_shipping": False,
            "effective_from": "2026-01-01T00:00:00Z",
        },
        customer_overrides={"email": "shopper-c2@example.com"},
        line_overrides={
            "size_label": "M",
            "quantity": 1,
            "unit_price_cents": 2295,
            "shipping_allocated_cents": 0,
            "delivered_at": "2026-05-28T00:00:00Z",
        },
    )
    lines = built["order_lines"]
    customer_id = built["customer"]["id"]

    first = fx.open_case(
        api, lines[0]["id"], customer_id, requested_reason_code="CHANGE_OF_MIND"
    )
    fx.classify_case(api, first["id"], "CHANGE_OF_MIND")
    built["first_case"] = fx.resolve_case(api, first["id"], "RESELLABLE_A")
    built["shopper_after_first"] = fx.read_customer(api, customer_id)

    second = fx.open_case(
        api, lines[1]["id"], customer_id, requested_reason_code="CHANGE_OF_MIND"
    )
    fx.classify_case(api, second["id"], "CHANGE_OF_MIND")
    built["second_case"] = fx.resolve_case(api, second["id"], "RESELLABLE_A")
    built["shopper_after_second"] = fx.read_customer(api, customer_id)

    built["first_window"] = first["effective_window_days"]
    built["second_window"] = second["effective_window_days"]
    return built


def test_each_change_of_mind_refund_pays_the_gross_and_withholds_no_fee(api):
    """PRD §3.8: "The restocking-fee tier is keyed on the order line's
    `gross_line_cents` and never on the refund, which is what keeps the pair well
    defined in a single pass: a gross below 5,000 cents carries a tier of 0 basis
    points, a gross from 5,000 cents up to but not including 20,000 cents carries
    1,000 basis points, and a gross of 20,000 cents or more carries 1,500 basis
    points."  A single 2,295-cent unit sits in the zero-basis-point tier, so both
    change-of-mind refunds return the whole gross even though the frozen policy does
    apply restocking, and each closure books 1,330 cents of handling cost against the
    item.

    Design: Corner/calculations/effective_window_days_floors_at_seven_for_restricted_customer
    """
    built = _build_shopper_with_two_change_of_mind_refunds(api)

    assert built["first_window"] == 10
    assert built["first_case"]["restocking_fee_cents"] == 0
    assert built["first_case"]["refund_amount_cents"] == 2295
    assert built["first_case"]["total_cost_cents"] == 1330

    assert built["second_window"] == 10
    assert built["second_case"]["restocking_fee_cents"] == 0
    assert built["second_case"]["refund_amount_cents"] == 2295

    item = fx.read_item(api, built["item"]["id"])
    assert item["units_sold_count"] == 3
    assert item["total_return_count"] == 2
    assert item["fit_return_count"] == 0
    assert item["chronic_return_score_bp"] == 0
    assert item["return_cost_accrued_cents"] == 2660


def test_the_second_strike_takes_the_shopper_from_watch_to_restricted(api):
    """PRD §3.8: "From those two numbers `abuse_status` follows: `BLOCKED` when
    `abuse_strike_count` is at least 3, **or** when `return_rate_bp` is at least 7,000
    and `purchase_line_count` is at least 4; otherwise `RESTRICTED` when
    `abuse_strike_count` is at least 2; otherwise `WATCH` when `abuse_strike_count` is
    at least 1; otherwise `CLEAR`."  One strike only reaches watch, which still buys
    the standard window; the second reaches the restricted rung, and three purchased
    lines keep the rate arm of the blocking rule out of reach — two cases over three
    lines is 6,666 basis points, and the rate arm needs four lines besides.

    Design: Corner/calculations/effective_window_days_floors_at_seven_for_restricted_customer
    """
    built = _build_shopper_with_two_change_of_mind_refunds(api)

    assert built["shopper_after_first"]["abuse_strike_count"] == 1
    assert built["shopper_after_first"]["abuse_status"] == "WATCH"
    assert built["shopper_after_first"]["policy_class"] == "STANDARD_WINDOW"

    after = built["shopper_after_second"]
    assert after["abuse_strike_count"] == 2
    assert after["abuse_status"] == "RESTRICTED"
    assert after["policy_class"] == "RESTRICTED_WINDOW"
    assert after["change_of_mind_count"] == 2
    assert after["purchase_line_count"] == 3
    assert after["return_rate_bp"] == 6666
    assert after["refunded_total_cents"] == 4590


def test_the_restricted_window_floors_at_seven_days_rather_than_going_negative(api):
    """PRD §3.7: "`effective_window_days` is the winner's `window_days` adjusted by the
    purchaser's `policy_class` and then floored at a hard minimum: a `STANDARD_WINDOW`
    shopper gets the base window unchanged, an `EXTENDED_WINDOW` shopper gets 30
    additional days, a `RESTRICTED_WINDOW` shopper loses 15 days, and whatever the
    arithmetic yields, the stored value is the larger of that result and 7 days."  Ten
    days less fifteen is minus five, which would close the return before it opened, so
    the third case stores seven days and a deadline seven days after delivery while
    still freezing the very same category default the earlier cases used.

    Design: Corner/calculations/effective_window_days_floors_at_seven_for_restricted_customer
    """
    built = _build_shopper_with_two_change_of_mind_refunds(api)
    third_line = built["order_lines"][2]

    case = validate_success(
        api.create_return_case(
            create_return_case_payload(
                third_line["id"], requested_reason_code="FIT_TOO_LARGE"
            ),
            make_customer_headers(built["customer"]["id"]),
        ),
        201,
    )

    assert case["effective_window_days"] == 7
    assert is_iso8601_timestamp(case["return_deadline_at"])
    assert case["return_deadline_at"].startswith("2026-06-04T00:00:00")
    assert case["effective_policy_id"] == built["policy"]["id"]
    assert case["status"] == "TRIAGE"

    shopper = fx.read_customer(api, built["customer"]["id"])
    assert shopper["return_case_count"] == 3
    assert shopper["abuse_status"] == "RESTRICTED"


def _build_shopper_carrying_a_wider_override(api: ApiClient) -> dict:
    """A shopper for whom two policy rows are live at once: the thirty-day category
    default every TOPS buyer gets, and a forty-five-day override written against this
    one profile."""
    built = fx.setup_listed_item(api, SCENARIO_START)
    built["default_policy"] = fx.create_policy(
        api, category_code="TOPS", **TOPS_THIRTY_DAY_POLICY
    )
    built["customer"] = fx.create_customer(api, email="shopper-c3@example.com")

    built["version_before_override"] = fx.read_customer(
        api, built["customer"]["id"]
    )["version"]
    built["override_policy"] = fx.create_override(
        api,
        built["customer"]["id"],
        built["version_before_override"],
        category_code="TOPS",
        window_days=45,
        restocking_applies=False,
        non_refundable_shipping=True,
        effective_from="2026-05-01T00:00:00Z",
    )
    built["version_after_override"] = fx.read_customer(
        api, built["customer"]["id"]
    )["version"]

    built["order_line"] = fx.create_order_line(
        api,
        built["customer"]["id"],
        built["item"]["id"],
        size_label="M",
        quantity=1,
        unit_price_cents=2295,
        shipping_allocated_cents=500,
        delivered_at="2026-05-20T00:00:00Z",
    )
    return built


def test_a_customer_override_outranks_the_category_default_at_the_same_clock(api):
    """PRD §3.7: "The candidates are then ranked: every `CUSTOMER_OVERRIDE` row
    outranks every `CATEGORY_DEFAULT` row; within one scope the later `effective_from`
    wins; and a remaining tie is broken by the later `created_at`, never by `id`."  The
    default has been in force since January and the override only since May, but scope
    is ranked before recency, so the case freezes the forty-five-day override and its
    deadline lands forty-five days after delivery rather than thirty.

    Design: Corner/calculations/customer_override_policy_outranks_category_default_on_case_creation
    """
    built = _build_shopper_carrying_a_wider_override(api)

    case = validate_success(
        api.create_return_case(
            create_return_case_payload(
                built["order_line"]["id"], requested_reason_code="FIT_TOO_SMALL"
            ),
            make_customer_headers(built["customer"]["id"]),
        ),
        201,
    )

    assert case["effective_policy_id"] == built["override_policy"]["id"]
    assert case["effective_policy_id"] != built["default_policy"]["id"]
    assert case["effective_window_days"] == 45
    assert is_iso8601_timestamp(case["return_deadline_at"])
    assert case["return_deadline_at"].startswith("2026-07-04T00:00:00")
    assert case["status"] == "TRIAGE"

    default_row = validate_success(
        api.get_return_policy(
            built["default_policy"]["id"], make_merch_ops_admin_headers()
        )
    )
    assert default_row["scope"] == "CATEGORY_DEFAULT"
    assert default_row["customer_profile_id"] is None


def test_writing_the_override_bumps_the_shoppers_profile_version_by_one(api):
    """PRD §3.7: "A customer override is authored against one shopper's profile; the
    row is stamped with `scope` `CUSTOMER_OVERRIDE`, its `customer_profile_id` is set
    to the profile it was authored under, and creating it increments that
    `CustomerProfile`'s `version` by 1 — which is exactly why the override write demands
    `expected_customer_profile_version` per §2.7."  The bump is the value a second
    override would have to present, and the shopper owns exactly one override row when
    the policy list is filtered down to that scope.

    Design: Corner/calculations/customer_override_policy_outranks_category_default_on_case_creation
    """
    built = _build_shopper_carrying_a_wider_override(api)

    assert built["version_after_override"] == built["version_before_override"] + 1
    assert built["override_policy"]["scope"] == "CUSTOMER_OVERRIDE"
    assert built["override_policy"]["customer_profile_id"] == built["customer"]["id"]
    assert built["override_policy"]["window_days"] == 45
    assert built["override_policy"]["non_refundable_shipping"] is True

    rows, meta = validate_paginated(
        api.list_return_policies(
            make_merch_ops_admin_headers(),
            {
                "customer_profile_id": built["customer"]["id"],
                "scope": "CUSTOMER_OVERRIDE",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [built["override_policy"]["id"]]


def _build_scheduled_deployment_over_a_prior_fit_return(api: ApiClient) -> dict:
    """A lever scheduled onto an item that already has history: four units delivered
    three weeks before the window opens, one of which has been refunded as a fit
    return well before the window opens too."""
    built = fx.setup_shopper_with_delivered_line(
        api,
        SCENARIO_START,
        policy_overrides=dict(TOPS_THIRTY_DAY_POLICY),
        customer_overrides={"email": "shopper-c4@example.com"},
        line_overrides={
            "size_label": "M",
            "quantity": 4,
            "unit_price_cents": 2295,
            "shipping_allocated_cents": 0,
            "delivered_at": "2026-06-10T00:00:00Z",
        },
    )
    built["intervention"] = fx.create_intervention(
        api,
        name="Standardize TOPS charts",
        lever="SIZE_CHART_STANDARDIZATION",
        unit_cost_cents=2000,
    )
    built["deployment"] = fx.create_deployment(
        api,
        built["intervention"]["id"],
        built["item"]["id"],
        window_start="2026-07-01T00:00:00Z",
        window_end="2026-08-01T00:00:00Z",
        spend_cents=2000,
    )

    fx.set_clock(api, "2026-06-15T00:00:00Z")
    case = fx.open_case(
        api,
        built["order_line"]["id"],
        built["customer"]["id"],
        requested_reason_code="FIT_TOO_SMALL",
    )
    fx.classify_case(api, case["id"], "FIT_TOO_SMALL")
    built["pre_window_case"] = fx.resolve_case(api, case["id"], "RESELLABLE_A")
    return built


def _walk_the_deployment_through_measurement(api: ApiClient, built: dict) -> dict:
    """Activate the deployment, deliver four more units inside its window, then take
    the checkpoints that close and measure it."""
    fx.set_clock(api, "2026-07-01T00:00:00Z")
    built["activation_run"] = fx.run_ops_run(api)

    fx.set_clock(api, "2026-07-05T00:00:00Z")
    built["in_window_line"] = fx.create_order_line(
        api,
        built["customer"]["id"],
        built["item"]["id"],
        size_label="M",
        quantity=4,
        unit_price_cents=2295,
        shipping_allocated_cents=0,
        delivered_at="2026-07-05T00:00:00Z",
    )

    fx.set_clock(api, "2026-08-01T00:00:00Z")
    built["termination_run"] = fx.run_ops_run(api)
    built["lever_mid_walk"] = fx.read_intervention(api, built["intervention"]["id"])
    built["measurement_run"] = fx.run_ops_run(api)
    return built


def test_the_baseline_snapshot_counts_only_units_delivered_before_the_window(api):
    """PRD §3.9: "The baseline is snapshotted at activation: `baseline_units_count` is
    the sum of `quantity` over the item's order lines whose `delivered_at` is strictly
    before `window_start`; the baseline fit-return count is the number of return cases
    on exactly those lines whose `reason_family` is `FIT`, whose `status` is
    `RESOLVED_REFUNDED`, and whose `requested_at` is strictly before `window_start`;
    and `baseline_return_rate_bp` is that count multiplied by 10,000, divided by
    `baseline_units_count`, with any fraction discarded, and is 0 when
    `baseline_units_count` is 0."  The four units delivered in June and the one fit
    return requested in June are the whole baseline, giving a rate of 2,500 basis
    points, and the checkpoint that snapshots it advances the deployment out of
    scheduled without closing or measuring anything.

    Design: Corner/calculations/deployment_baseline_excludes_in_window_units_and_measures_savings
    """
    built = _build_scheduled_deployment_over_a_prior_fit_return(api)

    assert built["deployment"]["status"] == "SCHEDULED"
    assert built["pre_window_case"]["status"] == "RESOLVED_REFUNDED"

    fx.set_clock(api, "2026-07-01T00:00:00Z")
    run = fx.run_ops_run(api)

    assert run["deployments_activated"] == 1
    assert run["deployments_terminated"] == 0
    assert run["deployments_measured"] == 0
    assert run["items_swept"] == 1
    assert run["chronic_flips"] == 0

    deployment = fx.read_deployment(api, built["deployment"]["id"])
    assert deployment["status"] == "ACTIVE"
    assert deployment["baseline_units_count"] == 4
    assert deployment["baseline_return_rate_bp"] == 2500


def test_walking_the_deployment_to_measured_takes_two_ops_runs(api):
    """PRD §3.9: "A `TERMINATED` deployment moves `TERMINATED → MEASURED`, but only on
    a *later* run than the one that terminated it — which means walking a deployment
    from `ACTIVE` all the way to `MEASURED` takes two ops-runs, not one."  The
    checkpoint that finds the window elapsed reports one closure and no measurement, so
    between the two runs the lever has recognized its whole spend against savings it
    has not been credited with yet and reads under review; only the next run measures
    it.

    Design: Corner/calculations/deployment_baseline_excludes_in_window_units_and_measures_savings
    """
    built = _walk_the_deployment_through_measurement(
        api, _build_scheduled_deployment_over_a_prior_fit_return(api)
    )

    assert built["termination_run"]["deployments_activated"] == 0
    assert built["termination_run"]["deployments_terminated"] == 1
    assert built["termination_run"]["deployments_measured"] == 0

    assert built["lever_mid_walk"]["spend_cents"] == 2000
    assert built["lever_mid_walk"]["gross_savings_cents"] == 0
    assert built["lever_mid_walk"]["net_savings_cents"] == -2000
    assert built["lever_mid_walk"]["funding_posture"] == "UNDER_REVIEW"

    assert built["measurement_run"]["deployments_terminated"] == 0
    assert built["measurement_run"]["deployments_measured"] == 1

    deployment = fx.read_deployment(api, built["deployment"]["id"])
    assert deployment["status"] == "MEASURED"
    assert deployment["terminated_reason_code"] == "WINDOW_ELAPSED"
    assert deployment["window_end"].startswith("2026-08-01T00:00:00")


def test_the_measurement_credits_one_avoided_return_at_the_tops_valuation(api):
    """PRD §3.9: "`avoided_return_count` is that improvement multiplied by
    `window_units_count`, divided by 10,000, with any fraction discarded — whole
    avoided returns only. `attributed_savings_cents` is `avoided_return_count`
    multiplied by the avoided-return valuation for the item's `category_code`: 3,200
    cents for `TOPS`, 3,600 for `BOTTOMS`, 4,200 for `DRESSES`, 5,200 for `OUTERWEAR`,
    and 4,400 for `FOOTWEAR`."  The four units delivered inside the half-open window
    carried no fit returns at all, so the improvement is the full 2,500 basis points of
    the baseline, one whole return is credited as avoided, and a tops item values it at
    3,200 cents — enough to carry the lever from under review to funded.

    Design: Corner/calculations/deployment_baseline_excludes_in_window_units_and_measures_savings
    """
    built = _walk_the_deployment_through_measurement(
        api, _build_scheduled_deployment_over_a_prior_fit_return(api)
    )

    deployment = fx.read_deployment(api, built["deployment"]["id"])
    assert deployment["window_units_count"] == 4
    assert deployment["measured_return_rate_bp"] == 0
    assert deployment["avoided_return_count"] == 1
    assert deployment["attributed_savings_cents"] == 3200

    lever = fx.read_intervention(api, built["intervention"]["id"])
    assert lever["spend_cents"] == 2000
    assert lever["gross_savings_cents"] == 3200
    assert lever["net_savings_cents"] == 1200
    assert lever["funding_posture"] == "FUNDED"
    assert lever["measured_deployment_count"] == 1
    assert lever["deployment_count"] == 1

    item = fx.read_item(api, built["item"]["id"])
    assert item["units_sold_count"] == 8
    assert item["fit_return_rate_bp"] == 1250
    assert item["chronic_return_score_bp"] == 937
    assert item["fit_watch_state"] == "NORMAL"

    in_window_line = fx.read_order_line(api, built["in_window_line"]["id"])
    assert in_window_line["status"] == "DELIVERED"


def _build_quality_review_case(api: ApiClient) -> dict:
    """One delivered unit whose defect complaint has been coded into the quality
    branch, waiting on a resolution."""
    built = fx.setup_shopper_with_delivered_line(
        api,
        SCENARIO_START,
        policy_overrides=dict(TOPS_THIRTY_DAY_POLICY),
        customer_overrides={"email": "shopper-c5@example.com"},
        line_overrides={
            "size_label": "M",
            "quantity": 1,
            "unit_price_cents": 2295,
            "shipping_allocated_cents": 0,
            "delivered_at": "2026-05-20T00:00:00Z",
        },
    )
    case = fx.open_case(
        api,
        built["order_line"]["id"],
        built["customer"]["id"],
        requested_reason_code="QUALITY_DEFECT",
    )
    built["case"] = fx.classify_case(api, case["id"], "QUALITY_DEFECT")
    return built


def test_the_quality_branch_appends_a_sixth_negative_posting(api):
    """PRD §3.8: "`VENDOR_CHARGEBACK_CREDIT` is written only for the `QUALITY` family
    and is the arithmetic negation of 4,000 basis points of the gross, divided by
    10,000, rounded half up; it is a credit because the vendor is being charged back."
    Only the quality branch writes that sixth row, so the ledger of a 2,295-cent gross
    runs 795, 1,054 for seventeen handling minutes, 34, 0 and 67 before closing on
    minus 918, and the signed sum is 1,032 cents.

    Design: Corner/calculations/quality_resolve_writes_negative_chargeback_and_penalizes_vendor
    """
    built = _build_quality_review_case(api)
    assert built["case"]["status"] == "QUALITY_REVIEW"

    case = validate_success(
        api.resolve_return_case(
            built["case"]["id"],
            resolve_return_case_payload("RESELLABLE_A"),
            make_returns_auditor_headers("auditor-2"),
        )
    )
    assert case["status"] == "RESOLVED_REFUNDED"
    assert case["refund_amount_cents"] == 2295
    assert case["total_cost_cents"] == 1032

    postings = fx.read_cost_postings(api, built["case"]["id"])
    assert len(postings) == 6
    assert [posting["component"] for posting in postings] == [
        "FREIGHT_INBOUND",
        "PROCESSING_LABOR",
        "REFURB_REPACK",
        "MARKDOWN_LOSS",
        "PAYMENT_FEE_UNRECOVERED",
        "VENDOR_CHARGEBACK_CREDIT",
    ]
    assert [posting["amount_cents"] for posting in postings] == [
        795,
        1054,
        34,
        0,
        67,
        -918,
    ]


def test_the_quality_close_debits_the_brands_reliability_by_five_hundred_points(api):
    """PRD §2.11: "The recomputation runs on every transition of one of the vendor's
    specifications into `CORRECTION_REQUESTED`, on every resolution of a quality-family
    return against one of the vendor's items, and on every void of such a case."  The
    resolution is a chargeback rather than a correction round, so the brand's round
    count is untouched while its reliability drops the single chargeback penalty to
    9,500 basis points — still comfortably active — and the item's fit counters stay at
    zero because a defect is not a fit complaint.

    Design: Corner/calculations/quality_resolve_writes_negative_chargeback_and_penalizes_vendor
    """
    built = _build_quality_review_case(api)

    fx.resolve_case(api, built["case"]["id"], "RESELLABLE_A")

    vendor = fx.read_vendor(api, built["vendor"]["id"])
    assert vendor["quality_chargeback_count"] == 1
    assert vendor["reliability_score_bp"] == 9500
    assert vendor["status"] == "ACTIVE"
    assert vendor["correction_round_count"] == 0

    item = fx.read_item(api, built["item"]["id"])
    assert item["total_return_count"] == 1
    assert item["fit_return_count"] == 0
    assert item["chronic_return_score_bp"] == 0
    assert item["fit_watch_state"] == "NORMAL"
    assert item["return_cost_accrued_cents"] == 1032
