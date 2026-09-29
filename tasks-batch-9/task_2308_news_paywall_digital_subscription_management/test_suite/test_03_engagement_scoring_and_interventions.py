"""Engagement decay, the two readings of the score, propensity refresh and interventions."""

from test_helpers import (
    OPS_AGENT_HEADERS,
    api_client,
    assert_billing_run_report,
    create_active_plan,
    create_registered_reader,
    invoice_for_cycle,
    log_event,
    make_reader_headers,
    open_subscription,
    read_reader,
    record_payment,
    run_billing,
    set_clock_date,
    start_cancellation,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as f


def _arrange_seven_day_old_reader_with_eight_points_of_engagement():
    """A young paid reader whose in-window events accumulate to exactly 8.00."""
    set_clock_date("2026-08-25")
    plan = create_active_plan(
        name="Digital Standard E",
        bundle_type="DIGITAL_ONLY",
        intro_price_cents=499,
        intro_cycles=1,
        standard_price_cents=1499,
        standard_from_cycle=2,
        cycle_days=30,
    )
    reader = create_registered_reader("reader2@mail.test", propensity_band="MEDIUM")
    headers = make_reader_headers(reader["id"])
    subscription = open_subscription(reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 499)
    log_event(reader["id"], "COMMENT_POST", headers, occurred_at="2026-08-26T00:00:00Z")
    log_event(reader["id"], "APP_OPEN", headers, occurred_at="2026-08-28T00:00:00Z")
    log_event(
        reader["id"], "NEWSLETTER_OPEN", headers, occurred_at="2026-08-30T00:00:00Z"
    )
    set_clock_date("2026-09-01")
    run_billing("ENGAGEMENT_ONLY")
    return {
        "plan": plan,
        "reader": reader,
        "reader_headers": headers,
        "subscription": subscription,
    }


def test_rolling_thirty_day_score_bands_the_young_reader_high_risk_and_low_propensity():
    """The stored rolling reading is 8.00, which bands churn HIGH and propensity LOW.

    PRD: "It is accumulated over all of that reader's events whose `occurred_at` lies inside a half-open thirty-day window ending at the clock instant: an event is in the window when the whole number of days between its `occurred_at` and the clock instant is at least zero and strictly less than thirty."
    PRD: "The accumulated total is rounded half up to two decimal places exactly once, after the summation is complete, and the result is stored on the reader."
    PRD: "`tenure_days` itself is the whole number of days between the reader's `created_at` and the clock instant, rounded down."
    PRD: "That pass walks every reader in `created_at` ascending order, rescores `engagement_score` against the current clock, re-derives `churn_risk_band`, resets any meter period that has aged past thirty days, and then re-bands propensity from the freshly written score: 30 or above becomes `HIGH`, from 10 up to but not including 30 becomes `MEDIUM`, and below 10 becomes `LOW`."

    Design: Difficulty/dual_variant_calc/engagement_rolling_30d_diverges_from_cohort_normalized
    """
    state = _arrange_seven_day_old_reader_with_eight_points_of_engagement()

    reader = read_reader(state["reader"]["id"])
    assert reader["tenure_days"] == 7
    assert float(reader["engagement_score"]) == 8.00
    assert reader["churn_risk_band"] == "HIGH"
    assert reader["propensity_band"] == "LOW"


def test_cohort_normalized_projection_frozen_on_the_request_diverges_from_the_rolling_score():
    """8.00 over a tenure of 7 days projects to 34.29, which is the richest tier.

    PRD: "When the reader's `tenure_days` is less than thirty, the cohort-normalized reading takes the accumulated total, multiplies it by thirty, divides by the greater of one and `tenure_days`, and rounds half up to two decimals; when `tenure_days` is thirty or more it is identical to the rolling reading."
    PRD: "It also freezes, once and for all, the cohort-normalized reading of the reader's engagement as `projected_engagement_score`, from which `eligible_save_offer_tier` is derived: `RICH` when the projection is 20 or above, `STANDARD` when it is at least 8 but below 20, and `MINIMAL` when it is below 8."
    PRD: "The request is created with `status` `INITIATED`, `save_offer_count` at 0 and `retained` false, and its `confirmed_on` and `effective_on` null."

    Design: Difficulty/dual_variant_calc/engagement_rolling_30d_diverges_from_cohort_normalized
    """
    state = _arrange_seven_day_old_reader_with_eight_points_of_engagement()

    request = start_cancellation(
        state["subscription"]["id"], "PRICE", state["reader_headers"]
    )

    assert float(request["projected_engagement_score"]) == 34.29
    assert request["eligible_save_offer_tier"] == "RICH"
    assert request["status"] == "INITIATED"
    rolling = float(read_reader(state["reader"]["id"])["engagement_score"])
    assert float(request["projected_engagement_score"]) != rolling


def _arrange_four_readers_at_the_engagement_edges():
    """One empty reader, one at exactly 10.00, one at 9.00 and one decayed to 1.25."""
    set_clock_date("2026-09-01")
    reader_a = create_registered_reader("ra@mail.test", propensity_band="MEDIUM")
    reader_b = create_registered_reader("rb@mail.test", propensity_band="MEDIUM")
    reader_c = create_registered_reader("rc@mail.test", propensity_band="MEDIUM")
    reader_d = create_registered_reader("rd@mail.test", propensity_band="MEDIUM")
    headers_b = make_reader_headers(reader_b["id"])
    headers_c = make_reader_headers(reader_c["id"])
    for _ in range(2):
        log_event(
            reader_b["id"], "COMMENT_POST", headers_b, occurred_at="2026-09-01T00:00:00Z"
        )
    log_event(
        reader_c["id"], "COMMENT_POST", headers_c, occurred_at="2026-09-01T00:00:00Z"
    )
    for _ in range(2):
        log_event(
            reader_c["id"],
            "NEWSLETTER_OPEN",
            headers_c,
            occurred_at="2026-09-01T00:00:00Z",
        )
    # Backfilling a past instant is the operations desk's prerogative.
    log_event(
        reader_d["id"], "COMMENT_POST", OPS_AGENT_HEADERS, occurred_at="2026-08-02T00:00:00Z"
    )
    log_event(
        reader_d["id"], "COMMENT_POST", OPS_AGENT_HEADERS, occurred_at="2026-08-03T00:00:00Z"
    )
    report = run_billing("ENGAGEMENT_ONLY")
    return {
        "reader_a": reader_a,
        "reader_b": reader_b,
        "reader_c": reader_c,
        "reader_d": reader_d,
        "report": report,
    }


def test_score_of_exactly_ten_bands_propensity_medium_while_nine_bands_low():
    """The propensity refresh treats 10.00 as inside MEDIUM and 9.00 as below it.

    PRD: "That pass walks every reader in `created_at` ascending order, rescores `engagement_score` against the current clock, re-derives `churn_risk_band`, resets any meter period that has aged past thirty days, and then re-bands propensity from the freshly written score: 30 or above becomes `HIGH`, from 10 up to but not including 30 becomes `MEDIUM`, and below 10 becomes `LOW`."
    PRD: "The class weights are: a granted article view counts 3, a newsletter open counts 2, an app open counts 1, and a posted comment counts 5, while a blocked article view, an editorial intervention, a product intervention and a price-increase notice all count 0 — blocked paywall hits and outbound messages never move the score."

    Design: Difficulty/boundary_precision_check/engagement_window_and_propensity_thresholds_at_the_edge
    """
    state = _arrange_four_readers_at_the_engagement_edges()

    reader_b = read_reader(state["reader_b"]["id"])
    assert float(reader_b["engagement_score"]) == 10.00
    assert reader_b["churn_risk_band"] == "HIGH"
    assert reader_b["propensity_band"] == "MEDIUM"

    reader_c = read_reader(state["reader_c"]["id"])
    assert float(reader_c["engagement_score"]) == 9.00
    assert reader_c["churn_risk_band"] == "HIGH"
    assert reader_c["propensity_band"] == "LOW"


def test_event_exactly_thirty_days_old_is_excluded_while_a_twenty_nine_day_event_decays_to_a_quarter():
    """The window is half-open, so only the 29-day event survives, at quarter weight.

    PRD: "Future-dated events and events thirty days old or older contribute nothing."
    PRD: "Each in-window event contributes the weight of its class multiplied by a decay factor of one half raised to the power of the event's age in whole days divided by ten, rounded down to a whole number — so events aged 0 through 9 days contribute at full weight, those aged 10 through 19 days at half weight, and those aged 20 through 29 days at a quarter weight."

    Design: Difficulty/boundary_precision_check/engagement_window_and_propensity_thresholds_at_the_edge
    """
    state = _arrange_four_readers_at_the_engagement_edges()

    reader_d = read_reader(state["reader_d"]["id"])
    assert float(reader_d["engagement_score"]) == 1.25
    assert reader_d["churn_risk_band"] == "SEVERE"
    assert reader_d["propensity_band"] == "LOW"


def test_reader_with_no_events_scores_zero_and_the_scoped_run_reports_only_rescored_readers():
    """The empty event set is a real band, and an ENGAGEMENT_ONLY run bills nothing.

    PRD: "A brand-new reader with no events scores 0.00 and is therefore `SEVERE` — the empty-set edge is a real band, not an error."
    PRD: "A pass that is out of scope contributes an empty array rather than being absent."

    Design: Difficulty/boundary_precision_check/engagement_window_and_propensity_thresholds_at_the_edge
    """
    state = _arrange_four_readers_at_the_engagement_edges()

    reader_a = read_reader(state["reader_a"]["id"])
    assert float(reader_a["engagement_score"]) == 0.00
    assert reader_a["churn_risk_band"] == "SEVERE"
    assert reader_a["propensity_band"] == "LOW"

    assert_billing_run_report(
        state["report"], "ENGAGEMENT_ONLY", non_empty=["readers_rescored"]
    )
    assert state["report"]["invoices_created"] == []
    assert state["reader_a"]["id"] in state["report"]["readers_rescored"]


def _arrange_low_risk_reader_with_six_comment_posts():
    """Six posted comments put the reader at 30.00, which is the LOW churn band."""
    set_clock_date("2026-09-01")
    reader = create_registered_reader("loyal@mail.test", propensity_band="MEDIUM")
    headers = make_reader_headers(reader["id"])
    for _ in range(6):
        log_event(
            reader["id"], "COMMENT_POST", headers, occurred_at="2026-09-01T00:00:00Z"
        )
    return {"reader": reader, "reader_headers": headers}


def test_editorial_intervention_is_refused_for_a_reader_whose_churn_band_is_low():
    """The gate is the parent reader's derived band, not anything in the event body.

    PRD: "An `INTERVENTION_EDITORIAL` or `INTERVENTION_PRODUCT` event may only be logged for a reader whose `churn_risk_band` is `HIGH` or `SEVERE`, and only while `intervention_count_in_period` is less than two; a reader whose band is `LOW` or `MEDIUM`, or whose count has already reached two, answers `ERR_INTERVENTION_NOT_WARRANTED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/intervention_cannot_be_logged_for_low_risk_reader_rejected
    """
    state = _arrange_low_risk_reader_with_six_comment_posts()
    assert read_reader(state["reader"]["id"])["churn_risk_band"] == "LOW"

    response = api_client.create_reader_event(
        state["reader"]["id"],
        f.create_reader_event_payload(
            "INTERVENTION_EDITORIAL", occurred_at="2026-09-01T00:00:00Z"
        ),
        OPS_AGENT_HEADERS,
    )

    validate_error(response, "ERR_INTERVENTION_NOT_WARRANTED", 422)


def test_refused_intervention_appends_no_event_row_and_leaves_the_period_count_at_zero():
    """Six weighted comments stand at 30.00 and the intervention budget is untouched.

    PRD: "`intervention_count_in_period` is the number of the reader's `INTERVENTION_EDITORIAL` and `INTERVENTION_PRODUCT` events whose `occurred_at` falls on or after `meter_period_started_on`, so the intervention budget refills whenever the meter period rolls over."

    Design: Difficulty/cross_entity_state_dependency/intervention_cannot_be_logged_for_low_risk_reader_rejected
    """
    state = _arrange_low_risk_reader_with_six_comment_posts()
    api_client.create_reader_event(
        state["reader"]["id"],
        f.create_reader_event_payload(
            "INTERVENTION_EDITORIAL", occurred_at="2026-09-01T00:00:00Z"
        ),
        OPS_AGENT_HEADERS,
    )

    reader = read_reader(state["reader"]["id"])
    assert float(reader["engagement_score"]) == 30.00
    assert reader["churn_risk_band"] == "LOW"
    assert reader["intervention_count_in_period"] == 0
    rows, meta = validate_paginated(
        api_client.list_reader_events(
            OPS_AGENT_HEADERS, {"reader_id": state["reader"]["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 6
    assert len(rows) == 6
