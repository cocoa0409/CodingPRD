"""Carrier standing over time: period scorecards and the two composite variants."""

from test_helpers import (
    DEFAULT_CLOCK,
    create_qualified_carrier,
    draft_scorecard,
    publish_scorecard,
    read_carrier,
    set_clock,
)

OLDER_PERIOD = {
    "period_start": "2026-01-01T00:00:00Z",
    "period_end": "2026-04-01T00:00:00Z",
    "on_time_pct": 92.00,
    "claims_ratio": 0.0100,
}
NEWER_PERIOD = {
    "period_start": "2026-04-01T00:00:00Z",
    "period_end": "2026-07-01T00:00:00Z",
    "on_time_pct": 55.00,
    "claims_ratio": 0.0800,
}


def _carrier_with_two_draft_scorecards():
    """A qualified carrier holding both measurement periods still in DRAFT."""
    set_clock(DEFAULT_CLOCK)
    carrier = create_qualified_carrier()
    older = draft_scorecard(carrier["id"], **OLDER_PERIOD)
    newer = draft_scorecard(carrier["id"], **NEWER_PERIOD)
    return carrier, older, newer


class TestPeriodScore:
    """The period score each scorecard carries in its own right."""

    def test_period_score_weights_on_time_acceptance_and_claims(self):
        """Each period scores from on-time, tender acceptance and the claims subscore.

        PRD §3.2: "When `period_tender_count` is zero, `tender_acceptance_pct` is
        `100.00` — a carrier that was never tendered in the period is not penalised for
        it."
        PRD §3.2: "Multiply `claims_ratio` by 1000, subtract that product from
        `100.00`, round to 2 decimal places, and then floor the result at `0.00` so it
        never goes negative."
        PRD §3.2: "Multiply `on_time_pct` by `0.45`, `tender_acceptance_pct` by `0.35`
        and the claims subscore by `0.20`, add the three products, and round to 2
        decimal places. That figure is the scorecard's `composite_score`."

        Design: Difficulty/dual_variant_calc/carrier_composite_provisional_versus_final_performance
        """
        _, older, newer = _carrier_with_two_draft_scorecards()

        assert older["tender_acceptance_pct"] == 100.00, (
            f"an untendered period is not penalised, "
            f"got {older['tender_acceptance_pct']}"
        )
        assert older["period_tender_count"] == 0, (
            f"no tenders were recorded in the period, got {older['period_tender_count']}"
        )
        assert older["composite_score"] == 94.40, (
            f"92.00 x 0.45 + 100.00 x 0.35 + 90.00 x 0.20 is 94.40, "
            f"got {older['composite_score']}"
        )
        assert newer["composite_score"] == 63.75, (
            f"55.00 x 0.45 + 100.00 x 0.35 + 20.00 x 0.20 is 63.75, "
            f"got {newer['composite_score']}"
        )


class TestCompositeVariants:
    """PROVISIONAL_SCREENING against FINAL_PERFORMANCE on the same carrier."""

    def test_composite_is_the_provisional_baseline_before_any_publication(self):
        """With no published scorecard the performance component is the flat baseline.

        PRD §3.2: "When the kept list holds at least one scorecard,
        `composite_score_variant` is `FINAL_PERFORMANCE`; when it is empty, the variant
        is `PROVISIONAL_SCREENING`."
        PRD §3.2: "Under `PROVISIONAL_SCREENING` the performance component is the fixed
        provisional baseline of `90.00`, since there is no evidence either way."
        PRD §3.2: "Drafting a scorecard does not touch the carrier in any way. A
        `DRAFT` scorecard is invisible to the carrier's own composite score."

        Design: Difficulty/dual_variant_calc/carrier_composite_provisional_versus_final_performance
        """
        carrier, _, _ = _carrier_with_two_draft_scorecards()
        carrier = read_carrier(carrier["id"])

        assert carrier["composite_score_variant"] == "PROVISIONAL_SCREENING", (
            f"two DRAFT scorecards do not enter the lookback, "
            f"got {carrier['composite_score_variant']}"
        )
        assert carrier["published_scorecard_count"] == 0, (
            f"a DRAFT scorecard does not count toward the lookback, "
            f"got {carrier['published_scorecard_count']}"
        )
        assert carrier["capability_score"] == 88.00, (
            f"100.00 x 0.40 + 60.00 x 0.30 + 100.00 x 0.30 is 88.00, "
            f"got {carrier['capability_score']}"
        )
        assert carrier["composite_score"] == 90.60, (
            f"90.00 x 0.70 + 88.00 x 0.20 + 100.00 x 0.10 is 90.60, "
            f"got {carrier['composite_score']}"
        )

    def test_first_publication_flips_the_variant_to_final_performance(self):
        """One published scorecard makes the performance component that period's score.

        PRD §3.2: "The first publication is what flips the variant: because the
        final-variant threshold is one scorecard, a carrier goes from
        `PROVISIONAL_SCREENING` to `FINAL_PERFORMANCE` as soon as its first scorecard
        is published."
        PRD §3.2: "With three scorecards the divisor is `1.00`; with two it is `0.80`;
        with one it is `0.50`, which makes a single-scorecard carrier's performance
        component equal to that scorecard's own score."
        PRD §3.2: "Multiply the performance component by `0.70`, the carrier's
        `capability_score` by `0.20` and the insurance component by `0.10`, add the
        three products, and round to 2 decimal places."

        Design: Difficulty/dual_variant_calc/carrier_composite_provisional_versus_final_performance
        """
        set_clock(DEFAULT_CLOCK)
        carrier = create_qualified_carrier()
        publish_scorecard(carrier["id"], **OLDER_PERIOD)
        carrier = read_carrier(carrier["id"])

        assert carrier["composite_score_variant"] == "FINAL_PERFORMANCE", (
            f"the first publication flips the variant, "
            f"got {carrier['composite_score_variant']}"
        )
        assert carrier["published_scorecard_count"] == 1, (
            f"one published scorecard participates in the lookback, "
            f"got {carrier['published_scorecard_count']}"
        )
        assert carrier["composite_score"] == 93.68, (
            f"94.40 x 0.70 + 88.00 x 0.20 + 100.00 x 0.10 is 93.68, "
            f"got {carrier['composite_score']}"
        )

    def test_second_publication_blends_both_periods_by_recency(self):
        """Two published periods are weighted 0.50 and 0.30 over a 0.80 divisor.

        PRD §3.2: "Take that carrier's scorecards whose `status` is `PUBLISHED` or
        `DISPUTED`, order them by `period_end` descending and then by `created_at`
        ascending, and keep at most the first three."
        PRD §3.2: "Under `FINAL_PERFORMANCE` the recency weights `0.50`, `0.30` and
        `0.20` are taken in order and truncated to the number of scorecards actually
        kept; each kept scorecard's `composite_score` is multiplied by its positional
        weight; the products are summed; that sum is divided by **the sum of the
        weights actually used**, not by 1.00; and the quotient is rounded to 2 decimal
        places."
        PRD §3.2: "A carrier whose `status` is `QUALIFIED` and whose new
        `composite_score` is strictly below `75.00` moves to `WATCHLIST`".

        Design: Difficulty/dual_variant_calc/carrier_composite_provisional_versus_final_performance
        """
        set_clock(DEFAULT_CLOCK)
        carrier = create_qualified_carrier()
        publish_scorecard(carrier["id"], **OLDER_PERIOD)
        publish_scorecard(carrier["id"], **NEWER_PERIOD)
        carrier = read_carrier(carrier["id"])

        assert carrier["published_scorecard_count"] == 2, (
            f"both published scorecards participate, "
            f"got {carrier['published_scorecard_count']}"
        )
        assert carrier["composite_score"] == 80.27, (
            "the newer period leads at 0.50 and the older follows at 0.30 over a 0.80 "
            f"divisor, giving 75.24 performance and 80.27 composite, "
            f"got {carrier['composite_score']}"
        )
        assert carrier["capability_score"] == 88.00, (
            f"publication does not touch the capability measurement, "
            f"got {carrier['capability_score']}"
        )
        assert carrier["status"] == "QUALIFIED", (
            f"80.27 is at or above the watchlist floor of 75.00 so the carrier stays "
            f"QUALIFIED, got {carrier['status']}"
        )
