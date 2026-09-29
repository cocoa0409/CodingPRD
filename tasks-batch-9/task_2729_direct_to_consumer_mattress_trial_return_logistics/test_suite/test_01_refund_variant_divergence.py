"""Divergence between the two refund variants and the two abuse-score variants.

Both rules in this module compute two figures from the same stored inputs and
prove the figures genuinely differ, so an implementation that keeps only one of
them is caught.
"""

from test_helpers import (
    create_customer_row,
    preload_abuse_signals,
    read_customer,
    read_refund_summary,
    set_clock,
    setup_return_lifecycle,
)


class TestRefundProrationVariantsDivergeAtFortyFiveNights:
    """A 120000-cent order collected on night 45 prices differently in each variant."""

    def test_inspection_stamps_the_usage_prorated_provisional_variant(self):
        """PRD §3.8: "The **provisional** variant, stamped at inspection, prorates by actual usage: it takes `gross_refundable_cents`, multiplies by whichever is smaller of `nights_used` and the model's `trial_nights`, multiplies by a flat usage-retention rate of 2500 basis points, divides by the model's `trial_nights` multiplied by 10000, and rounds the single resulting quantity to the nearest whole cent with ties away from zero."

        Delivery on 2026-08-01 and collection on 2026-09-15 is 45 complete
        nights, so the linear deduction on the 120000-cent principal is
        120000 * 45 * 2500 / (100 * 10000) = 13500 cents and the provisional
        refund is 120000 - 13500 = 106500 cents.

        Design: Difficulty/dual_variant_calc/refund_proration_provisional_usage_vs_final_tier_diverge_at_45_nights
        """
        scenario = setup_return_lifecycle(stage="INSPECTED")
        case = scenario["return_case"]

        assert case["nights_used"] == 45, (
            f"nights_used should be the 45 complete days between delivery and "
            f"pickup, got {case['nights_used']}"
        )
        assert case["proration_deduction_cents"] == 13500, (
            "at inspection the case carries the provisional, usage-linear "
            f"proration of 13500 cents, got {case['proration_deduction_cents']}"
        )
        assert case["provisional_refund_cents"] == 106500
        assert case["bundle_unwind_cents"] == 0
        assert case["damage_offset_cents"] == 0

    def test_authorization_overwrites_the_proration_with_the_tier_banded_final_variant(self):
        """PRD §3.9: "On the return case, `final_refund_cents` is stamped with the net figure, `proration_deduction_cents` is **overwritten** with the final-variant value — replacing the provisional figure written at inspection — the money axis moves `PENDING → AUTHORIZED`, and the case's `version` increments by one."

        45 nights sits in the 31-to-60 band, which retains a flat 500 basis
        points: 120000 * 500 / 10000 = 6000 cents, so the net refund is 114000
        cents and the 13500-cent provisional deduction is replaced by 6000.

        Design: Difficulty/dual_variant_calc/refund_proration_provisional_usage_vs_final_tier_diverge_at_45_nights
        """
        scenario = setup_return_lifecycle(stage="AUTHORIZED")
        refund = scenario["refund"]
        case = scenario["return_case"]

        assert refund["gross_refundable_cents"] == 120000
        assert refund["proration_deduction_cents"] == 6000, (
            "the final variant prorates by the flat 500-bps band for 45 nights, "
            f"got {refund['proration_deduction_cents']}"
        )
        assert refund["net_refund_cents"] == 114000
        assert refund["status"] == "AUTHORIZED"
        assert case["final_refund_cents"] == 114000
        assert case["proration_deduction_cents"] == 6000, (
            "the case's proration_deduction_cents must be overwritten with the "
            f"final figure, got {case['proration_deduction_cents']}"
        )
        assert case["financial_status"] == "AUTHORIZED"

    def test_the_refund_summary_reports_the_delta_between_the_two_variants(self):
        """PRD §3.8: "A computed read on the return case exposes exactly this, reporting `variant_in_effect`, `gross_refundable_cents`, `proration_deduction_cents`, `bundle_unwind_cents`, `damage_offset_cents`, `provisional_refund_cents`, `final_refund_cents` and `variant_delta_cents`, the difference between the two variants."

        Once the money has been authorized the effective variant is FINAL, and
        the two figures 106500 and 114000 differ by 7500 cents.

        Design: Difficulty/dual_variant_calc/refund_proration_provisional_usage_vs_final_tier_diverge_at_45_nights
        """
        scenario = setup_return_lifecycle(stage="AUTHORIZED")
        summary = read_refund_summary(scenario["return_case"]["id"])

        assert summary["variant_in_effect"] == "FINAL"
        assert summary["provisional_refund_cents"] == 106500
        assert summary["final_refund_cents"] == 114000
        assert abs(summary["variant_delta_cents"]) == 7500, (
            "variant_delta_cents is the difference between the two variant "
            f"figures, got {summary['variant_delta_cents']}"
        )


class TestAbuseScoreRollingDecayVersusLifetime:
    """One 212-day-old signal and one fresh signal split the two score variants."""

    def test_the_rolling_variant_halves_a_signal_past_one_hundred_and_eighty_days(self):
        """PRD §3.2: "Under the rolling variant — which is the variant that gates behaviour — a signal younger than 180 days contributes its full type weight; a signal at least 180 days old but younger than 365 days contributes half its type weight, rounded to the nearest whole point with ties away from zero; and a signal 365 days old or older contributes nothing at all."

        A HOUSEHOLD_MATCH dated 2026-01-01 is 212 days old at the epoch clock of
        2026-08-01, so it contributes 15 of its 30 points, while the
        REPEAT_RETURN dated 2026-07-01 is 31 days old and contributes all 25:
        the rolling total is 40.

        Design: Difficulty/dual_variant_calc/abuse_score_rolling_decay_vs_lifetime_diverge_on_212_day_old_signal
        """
        customer = create_customer_row(email="dv2@example.com", household_hash="HH-DV2")
        preload_abuse_signals(
            customer["id"],
            [
                ("HOUSEHOLD_MATCH", "2026-01-01T00:00:00Z"),
                ("REPEAT_RETURN", "2026-07-01T00:00:00Z"),
            ],
        )

        loaded = read_customer(customer["id"])
        assert loaded["abuse_score_rolling"] == 40, (
            f"rolling should halve the 212-day-old 30-point signal, got "
            f"{loaded['abuse_score_rolling']}"
        )
        assert loaded["signal_count"] == 2

    def test_the_lifetime_variant_ignores_age_entirely(self):
        """PRD §3.2: "Under the lifetime variant, every signal contributes its full type weight regardless of age."

        The same two signals sum to 30 + 25 = 55 lifetime points at the epoch
        clock, and a rolling total of 40 leaves the customer below the
        restriction threshold, so the posture is still ACTIVE with no block.

        Design: Difficulty/dual_variant_calc/abuse_score_rolling_decay_vs_lifetime_diverge_on_212_day_old_signal
        """
        customer = create_customer_row(email="dv2@example.com", household_hash="HH-DV2")
        preload_abuse_signals(
            customer["id"],
            [
                ("HOUSEHOLD_MATCH", "2026-01-01T00:00:00Z"),
                ("REPEAT_RETURN", "2026-07-01T00:00:00Z"),
            ],
        )

        loaded = read_customer(customer["id"])
        assert loaded["abuse_score_lifetime"] == 55, (
            f"lifetime ignores decay and sums 30 + 25, got "
            f"{loaded['abuse_score_lifetime']}"
        )
        assert loaded["status"] == "ACTIVE"
        assert loaded["trial_block_until"] is None

    def test_advancing_the_clock_decays_the_rolling_score_but_never_the_lifetime_score(self):
        """PRD §3.2: "The lifetime figure is reported to operators and never used as a gate; it is monotonically non-decreasing, and it diverges from the rolling figure as soon as any signal crosses 180 days of age."

        At 2027-01-02 the 2026-01-01 signal is 366 days old and drops out
        entirely, while the 2026-07-01 signal is 185 days old and halves 25 to
        13 points: rolling falls to 13 while lifetime stays at 55.

        Design: Difficulty/dual_variant_calc/abuse_score_rolling_decay_vs_lifetime_diverge_on_212_day_old_signal
        """
        customer = create_customer_row(email="dv2@example.com", household_hash="HH-DV2")
        preload_abuse_signals(
            customer["id"],
            [
                ("HOUSEHOLD_MATCH", "2026-01-01T00:00:00Z"),
                ("REPEAT_RETURN", "2026-07-01T00:00:00Z"),
            ],
        )

        set_clock("2027-01-02T00:00:00Z")
        loaded = read_customer(customer["id"])

        assert loaded["abuse_score_rolling"] == 13, (
            "the 366-day-old signal contributes nothing and the 185-day-old "
            f"25-point signal halves to 13, got {loaded['abuse_score_rolling']}"
        )
        assert loaded["abuse_score_lifetime"] == 55
        assert loaded["signal_count"] == 2
