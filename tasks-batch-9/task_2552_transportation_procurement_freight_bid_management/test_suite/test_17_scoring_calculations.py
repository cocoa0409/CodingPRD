"""Carrier and period scoring, where the clamps and the caps are the answer.

Each figure here is chosen so that the obvious wrong implementation lands on a
different, computable number: a capability screening that reads its verdict off
the score alone would pass, an unclamped claims subscore would sink the period
score by ten points, a closed tender window would halve the period's acceptance,
and a directly computed acceptance percentage would not be the complement of the
rounded rejection percentage.
"""

from test_helpers import (
    CATEGORY_MANAGER,
    CLOCK_GO_LIVE,
    COMPLIANCE,
    DEFAULT_CLOCK,
    api_client,
    append_tender,
    assert_same_instant,
    create_screened_review,
    decision_payload,
    draft_scorecard,
    read_allocation,
    read_carrier,
    read_rate_record,
    set_clock,
    setup_live_rate_record,
    validate_paginated,
    validate_success,
)

# ── One required mode the carrier cannot haul, behind two capped inputs ───────

#: The shipper needs dry van and reefer; the carrier under test hauls dry van.
TWO_MODE_REVIEW = {"required_modes": ["DRY_VAN", "REEFER"]}
#: 400 power units against the 200-unit target: 200.00 before the cap.
OVERSIZED_FLEET = {"fleet_power_units": 400}

# 50.00 x 0.40 + 100.00 x 0.30 + 100.00 x 0.30.
HALF_COVERAGE_CAPABILITY_SCORE = 80.00
CAPABILITY_PASS_FLOOR = 70.00
# 0.70 x 90.00 provisional + 0.20 x 80.00 capability + 0.10 x 100.00 insurance.
CONDITIONAL_COMPOSITE = 89.00
CONDITIONAL_NOTE = "DRY_VAN only; reefer capability to be added"

# ── A claims ratio that drives the subscore below zero ───────────────────────

CLAIMS_HEAVY_PERIOD = {"on_time_pct": 92.00, "claims_ratio": 0.1500}
# 0.45 x 92.00 + 0.35 x 100.00 + 0.20 x 0.00.
CLAMPED_PERIOD_SCORE = 76.40
#: What an unclamped subscore of -50.00 would have produced.
UNCLAMPED_PERIOD_SCORE = 66.40
# 0.70 x 76.40 + 0.20 x 88.00 + 0.10 x 100.00.
COMPOSITE_AFTER_CLAMPED_PERIOD = 81.08
WATCHLIST_FLOOR = 75.00

# ── A tender stamped exactly at period_end ───────────────────────────────────

BOUNDARY_PERIOD = {
    "period_start": CLOCK_GO_LIVE,
    "period_end": "2026-10-01T00:00:00Z",
    "on_time_pct": 90.00,
    "claims_ratio": 0.0100,
}
INSIDE_PERIOD_CLOCK = "2026-09-15T00:00:00Z"
PERIOD_END_CLOCK = "2026-10-01T00:00:00Z"
INSIDE_LOAD_REFERENCE = "LD-4001"
BOUNDARY_LOAD_REFERENCE = "LD-4002"
# 0.45 x 90.00 + 0.35 x 100.00 + 0.20 x 90.00.
BOUNDARY_PERIOD_SCORE = 93.50
#: What counting the period-end rejection would have produced instead.
CLOSED_WINDOW_ACCEPTANCE_PCT = 50.00
# 0.70 x 93.50 + 0.20 x 88.00 + 0.10 x 100.00.
COMPOSITE_AFTER_BOUNDARY_PERIOD = 93.05

# ── One rejection in three tenders ───────────────────────────────────────────

THIRD_LOAD_REFERENCE = "LD-4003"
ONE_OF_THREE_REJECTION_PCT = 33.33
ONE_OF_THREE_ACCEPTANCE_PCT = 66.67
MIN_TENDER_SAMPLE = 5


def _screen_two_mode_review():
    """A SCREENED review whose capability arm has already been run."""
    set_clock(DEFAULT_CLOCK)
    return create_screened_review(
        carrier_overrides=dict(OVERSIZED_FLEET),
        review_overrides=dict(TWO_MODE_REVIEW),
    )


def _decide(review_id, outcome, **overrides):
    """Records a decision without asserting the outcome."""
    return api_client.decide_qualification_review(
        review_id, decision_payload(outcome=outcome, **overrides), COMPLIANCE
    )


def _publish(scorecard_id):
    return validate_success(api_client.publish_scorecard(scorecard_id, CATEGORY_MANAGER))


def _count_mini_bids(lane_id):
    _rows, meta = validate_paginated(
        api_client.list_mini_bids(CATEGORY_MANAGER, {"lane_id": lane_id})
    )
    return meta["total_count"]


class TestCapabilityResultIsAnAndOfTwoConditions:
    """A screening that reads its verdict off the score alone gets this wrong."""

    def test_the_verdict_is_fail_although_the_score_clears_the_floor(self):
        """80.00 is comfortably above 70.00, and the mode subset still fails.

        PRD §3.1: "Multiply the mode coverage by `0.40`, the fleet adequacy by `0.30`
        and the insurance headroom by `0.30`, add the three products, and round to 2
        decimal places."
        PRD §3.1: "Divide `fleet_power_units` by the fleet target of 200 power units,
        multiply by `100.00`, round to 2 decimal places, and then cap the result at
        `100.00`."
        PRD §3.1: "The result is `PASS` when the review's `required_modes` are all
        contained in the carrier's `service_modes` **and** the computed
        `capability_score` is greater than or equal to the capability pass floor of
        `70.00`; otherwise it is `FAIL`."
        PRD §3.1: "The carrier's own `capability_score` is updated to the computed figure
        **whether the result is `PASS` or `FAIL`**"

        Design: Corner/calculations/capability_result_fails_on_mode_coverage_even_when_the_score_clears_the_floor
        """
        carrier, review = _screen_two_mode_review()
        assert float(review["capability_score"]) == HALF_COVERAGE_CAPABILITY_SCORE
        assert float(review["capability_score"]) >= CAPABILITY_PASS_FLOOR
        assert review["capability_result"] == "FAIL", (
            "one of the two required modes is outside the carrier's service_modes"
        )
        assert review["insurance_result"] == "PASS"
        assert review["status"] == "SCREENED"
        assert_same_instant(
            review["capability_screened_at"], DEFAULT_CLOCK, "capability_screened_at"
        )

        screened = read_carrier(carrier["id"])
        assert float(screened["capability_score"]) == HALF_COVERAGE_CAPABILITY_SCORE, (
            "the measurement is recorded on the carrier even though it failed"
        )
        assert screened["status"] == "SCREENING"

    def test_the_conditional_approval_composes_the_failed_capability_score(self):
        """89.00 carries the 80.00 forward: the failure is priced, not discarded.

        PRD §3.1: "**`APPROVE_CONDITIONAL`** requires that `insurance_result` is `PASS`
        **and** `capability_result` is `FAIL` — that is, the carrier is properly insured
        but does not clear the capability floor."
        PRD §3.2: "Under `PROVISIONAL_SCREENING` the performance component is the fixed
        provisional baseline of `90.00`, since there is no evidence either way."
        PRD §3.2: "Multiply the performance component by `0.70`, the carrier's
        `capability_score` by `0.20` and the insurance component by `0.10`, add the three
        products, and round to 2 decimal places."
        PRD §3.2: "When the kept list holds at least one scorecard,
        `composite_score_variant` is `FINAL_PERFORMANCE`; when it is empty, the variant
        is `PROVISIONAL_SCREENING`."

        Design: Corner/calculations/capability_result_fails_on_mode_coverage_even_when_the_score_clears_the_floor
        """
        carrier, review = _screen_two_mode_review()
        decided = validate_success(
            _decide(review["id"], "APPROVE_CONDITIONAL", decision_note=CONDITIONAL_NOTE)
        )
        assert decided["status"] == "CONDITIONALLY_APPROVED"
        assert decided["decision_outcome"] == "APPROVE_CONDITIONAL"
        assert decided["decision_note"] == CONDITIONAL_NOTE

        qualified = read_carrier(carrier["id"])
        assert qualified["status"] == "CONDITIONALLY_QUALIFIED"
        assert float(qualified["capability_score"]) == HALF_COVERAGE_CAPABILITY_SCORE
        assert float(qualified["composite_score"]) == CONDITIONAL_COMPOSITE
        assert qualified["composite_score_variant"] == "PROVISIONAL_SCREENING"
        assert qualified["published_scorecard_count"] == 0
        assert_same_instant(qualified["qualified_at"], DEFAULT_CLOCK, "qualified_at")


class TestClaimsSubscoreClampsAtZero:
    """A 0.1500 claims ratio overshoots the subscore's floor by fifty points."""

    def test_the_overshoot_is_absorbed_at_zero_and_eats_no_other_component(self):
        """76.40 keeps the whole on-time and acceptance contribution intact.

        PRD §3.2: "Multiply `claims_ratio` by 1000, subtract that product from `100.00`,
        round to 2 decimal places, and then floor the result at `0.00` so it never goes
        negative."
        PRD §3.2: "Multiply `on_time_pct` by `0.45`, `tender_acceptance_pct` by `0.35`
        and the claims subscore by `0.20`, add the three products, and round to 2 decimal
        places."
        PRD §3.2: "When `period_tender_count` is zero, `tender_acceptance_pct` is
        `100.00` — a carrier that was never tendered in the period is not penalised for
        it."

        Design: Corner/calculations/scorecard_claims_subscore_clamps_at_zero_instead_of_going_negative
        """
        set_clock(DEFAULT_CLOCK)
        carrier, review = create_screened_review()
        validate_success(_decide(review["id"], "APPROVE"))
        assert float(read_carrier(carrier["id"])["capability_score"]) == 88.00

        scorecard = draft_scorecard(carrier["id"], **CLAIMS_HEAVY_PERIOD)
        assert scorecard["period_tender_count"] == 0
        assert float(scorecard["tender_acceptance_pct"]) == 100.00
        assert float(scorecard["composite_score"]) == CLAMPED_PERIOD_SCORE
        assert float(scorecard["composite_score"]) != UNCLAMPED_PERIOD_SCORE, (
            "an unclamped subscore of -50.00 would have cost a further ten points"
        )

    def test_publishing_the_clamped_period_leaves_the_carrier_above_the_floor(self):
        """81.08 is what the clamp buys: below it the watchlist link would fire.

        PRD §3.2: "Publication requires that the scorecard's `period_end` is at or before
        the current clock instant — an unfinished period cannot be published."
        PRD §3.2: "with one it is `0.50`, which makes a single-scorecard carrier's
        performance component equal to that scorecard's own score"
        PRD §3.2: "A carrier whose `status` is `QUALIFIED` and whose new
        `composite_score` is strictly below `75.00` moves to `WATCHLIST`, with
        `status_reason` set to `SCORECARD_BELOW_FLOOR`."

        Design: Corner/calculations/scorecard_claims_subscore_clamps_at_zero_instead_of_going_negative
        """
        set_clock(DEFAULT_CLOCK)
        carrier, review = create_screened_review()
        validate_success(_decide(review["id"], "APPROVE"))
        scorecard = draft_scorecard(carrier["id"], **CLAIMS_HEAVY_PERIOD)

        published = _publish(scorecard["id"])
        assert published["status"] == "PUBLISHED"
        assert_same_instant(published["published_at"], DEFAULT_CLOCK, "published_at")
        assert float(published["composite_score"]) == CLAMPED_PERIOD_SCORE

        rescored = read_carrier(carrier["id"])
        assert rescored["published_scorecard_count"] == 1
        assert rescored["composite_score_variant"] == "FINAL_PERFORMANCE"
        assert float(rescored["composite_score"]) == COMPOSITE_AFTER_CLAMPED_PERIOD
        assert float(rescored["composite_score"]) >= WATCHLIST_FLOOR
        assert rescored["status"] == "QUALIFIED"
        assert rescored["status_reason"] is None


class TestScorecardTenderWindowIsHalfOpen:
    """The period owns its opening instant and disowns its closing one."""

    @staticmethod
    def _record_with_a_boundary_rejection():
        """A LIVE record with one acceptance inside the period and one exactly at its end."""
        ctx = setup_live_rate_record()
        set_clock(INSIDE_PERIOD_CLOCK)
        append_tender(
            ctx["rate_record"]["id"], INSIDE_LOAD_REFERENCE, outcome="ACCEPTED"
        )
        set_clock(PERIOD_END_CLOCK)
        append_tender(
            ctx["rate_record"]["id"],
            BOUNDARY_LOAD_REFERENCE,
            outcome="REJECTED",
            reject_reason="No capacity",
        )
        return ctx

    def test_the_period_end_rejection_belongs_to_the_next_period(self):
        """One tender in the window, so acceptance reads 100.00 and not 50.00.

        PRD §3.2: "Take every tender event recorded against a rate record belonging to
        this carrier whose `tendered_at` falls inside the **half-open** window from
        `period_start` inclusive to `period_end` exclusive."
        PRD §3.2: "A tender stamped exactly at `period_start` is in the period; a tender
        stamped exactly at `period_end` belongs to the next period, not this one."
        PRD §3.2: "Otherwise divide the number of those tenders whose `outcome` is
        `ACCEPTED` by `period_tender_count`, multiply by `100.00`, and round to 2 decimal
        places."

        Design: Corner/calculations/scorecard_tender_window_is_half_open_so_a_period_end_tender_is_excluded
        """
        ctx = self._record_with_a_boundary_rejection()

        scorecard = draft_scorecard(ctx["carrier"]["id"], **BOUNDARY_PERIOD)
        assert scorecard["period_tender_count"] == 1
        assert float(scorecard["tender_acceptance_pct"]) == 100.00
        assert (
            float(scorecard["tender_acceptance_pct"]) != CLOSED_WINDOW_ACCEPTANCE_PCT
        ), "a closed window would have counted the period-end rejection"
        assert float(scorecard["composite_score"]) == BOUNDARY_PERIOD_SCORE

    def test_the_records_own_metrics_count_both_tenders_at_the_same_instant(self):
        """The record has no period filter, so the two figures legitimately disagree.

        PRD §3.9: "`rejection_pct` is `0.00` when `tender_count` is zero; otherwise
        multiply `rejection_count` by `100.00`, divide by `tender_count`, and round to 2
        decimal places."
        PRD §3.9: "A record with 4 tenders of which all 4 were rejected has a
        `rejection_pct` of `100.00` but has not met the sample gate, so it is **not** at
        risk — a small sample is not evidence."
        PRD §3.2: "The selection deliberately ignores the current status of the rate
        record the tender sits on, so tenders on records that have since been superseded
        or rolled back still count toward the period in which they occurred."

        Design: Corner/calculations/scorecard_tender_window_is_half_open_so_a_period_end_tender_is_excluded
        """
        ctx = self._record_with_a_boundary_rejection()
        scorecard = draft_scorecard(ctx["carrier"]["id"], **BOUNDARY_PERIOD)

        record = read_rate_record(ctx["rate_record"]["id"])
        assert record["tender_count"] == 2
        assert record["rejection_count"] == 1
        assert float(record["rejection_pct"]) == CLOSED_WINDOW_ACCEPTANCE_PCT
        assert float(record["acceptance_pct"]) == CLOSED_WINDOW_ACCEPTANCE_PCT
        assert record["tender_count"] < MIN_TENDER_SAMPLE
        assert record["status"] == "LIVE", "the sample gate holds the risk cascade back"
        assert read_allocation(ctx["allocation"]["id"])["status"] == "ACTIVE"

        published = _publish(scorecard["id"])
        assert float(published["composite_score"]) == BOUNDARY_PERIOD_SCORE
        rescored = read_carrier(ctx["carrier"]["id"])
        assert float(rescored["composite_score"]) == COMPOSITE_AFTER_BOUNDARY_PERIOD
        assert rescored["composite_score_variant"] == "FINAL_PERFORMANCE"


class TestRejectionPctRoundsOneOfThree:
    """The repeating decimal is rounded once, and acceptance is its complement."""

    def test_the_pair_reads_33_33_and_66_67_and_still_sums_to_one_hundred(self):
        """0.00/100.00, then 50.00/50.00, then 33.33/66.67 across three appends.

        PRD §3.9: "`acceptance_pct` is `100.00` minus `rejection_pct`, rounded to 2
        decimal places, so the two always sum to exactly `100.00`."
        PRD §3.9: "`rejection_count` is the number of those whose `outcome` is `REJECTED`
        or `TIMEOUT`."
        PRD §3.9: "The record is **at risk** when two conditions hold **independently and
        together**: `tender_count` is greater than or equal to the minimum sample of 5,
        and `rejection_pct` is greater than or equal to the at-risk threshold of `20.00`."

        Design: Corner/calculations/tender_rejection_pct_rounds_one_of_three_to_two_decimals
        """
        ctx = setup_live_rate_record()
        record_id = ctx["rate_record"]["id"]

        append_tender(record_id, "LD-4001", outcome="ACCEPTED")
        first = read_rate_record(record_id)
        assert float(first["rejection_pct"]) == 0.00
        assert float(first["acceptance_pct"]) == 100.00

        append_tender(
            record_id, "LD-4002", outcome="REJECTED", reject_reason="No capacity"
        )
        second = read_rate_record(record_id)
        assert float(second["rejection_pct"]) == 50.00
        assert float(second["acceptance_pct"]) == 50.00

        third_event = append_tender(record_id, THIRD_LOAD_REFERENCE, outcome="ACCEPTED")
        assert third_event["position_used"] == "PRIMARY"
        assert_same_instant(third_event["tendered_at"], CLOCK_GO_LIVE, "tendered_at")

        third = read_rate_record(record_id)
        assert third["tender_count"] == 3
        assert third["rejection_count"] == 1
        assert float(third["rejection_pct"]) == ONE_OF_THREE_REJECTION_PCT
        assert float(third["acceptance_pct"]) == ONE_OF_THREE_ACCEPTANCE_PCT
        assert (
            float(third["rejection_pct"]) + float(third["acceptance_pct"]) == 100.00
        ), "acceptance is the complement of the rounded rejection, not its own quotient"

    def test_the_sample_gate_holds_the_record_live_at_a_third_rejected(self):
        """33.33 is over the 20.00 threshold and three tenders are under the sample.

        PRD §3.9: "Both gates matter."
        PRD §3.9: "The rate record moves from `LIVE` to `AT_RISK`."
        PRD §3.9: "A mini-bid is created automatically, with `origin` `SYSTEM`, `status`
        `REQUESTED`, `trigger_reason` `TENDER_REJECTION_RATE`"

        Design: Corner/calculations/tender_rejection_pct_rounds_one_of_three_to_two_decimals
        """
        ctx = setup_live_rate_record()
        record_id = ctx["rate_record"]["id"]
        append_tender(record_id, "LD-4001", outcome="ACCEPTED")
        append_tender(
            record_id, "LD-4002", outcome="REJECTED", reject_reason="No capacity"
        )
        append_tender(record_id, THIRD_LOAD_REFERENCE, outcome="ACCEPTED")

        record = read_rate_record(record_id)
        assert float(record["rejection_pct"]) >= 20.00
        assert record["tender_count"] < MIN_TENDER_SAMPLE
        assert record["status"] == "LIVE"
        assert read_allocation(ctx["allocation"]["id"])["status"] == "ACTIVE"
        assert _count_mini_bids(ctx["lane"]["id"]) == 0, (
            "no rebid window may open until both risk gates are met"
        )
