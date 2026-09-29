"""Two calculations that each exist in two variants on the same row.

The commission on one engagement is computed once provisionally at execution
and once finally at delivery; a speaker's performance is computed once with
recency weighting and once as a flat mean over the very same feedback rows.
"""

import pytest

from test_helpers import (
    assert_remittance_nets_out,
    read_engagement,
    read_speaker,
    round_half_up,
    setup_contracted_engagement,
    setup_delivered_engagement,
    setup_two_delivered_engagements,
    validate_success,
)

RECORDING_CONTRACT = {
    "travel_policy_code": "POLICY_A",
    "recording_rights": "FULL_BUY_OUT",
    "recording_fee_cents": 350_000,
    "technical_rider_code": "STAGE_PLUS",
    "exclusivity_days": 90,
}
BUY_OUT_OPTION = {"travel_allowance_cents": 70_000}


class TestProvisionalVersusFinalCommission:
    def test_execution_prices_only_the_fee_line_and_leaves_the_final_figure_unwritten(
        self, api, agent_headers
    ):
        """A buy-out engagement is priced provisionally at execution on the fee alone.

        PRD: `provisional_commission_cents` is then written as the provisional variant of the commission calculation: `quoted_fee_cents` multiplied by `commission_pct_snapshot`, that single product rounded half up to a whole number of cents.
        Design: Difficulty/dual_variant_calc/dual_variant_commission_provisional_versus_final_same_engagement
        """
        bundle = setup_contracted_engagement(
            api,
            contract_overrides=RECORDING_CONTRACT,
            option_overrides=BUY_OUT_OPTION,
        )
        engagement = bundle["engagement"]

        assert engagement["booking_status"] == "CONTRACTED"
        assert engagement["commission_pct_snapshot"] == pytest.approx(0.25, abs=0.001)
        assert engagement["provisional_commission_cents"] == 318_750
        assert engagement["provisional_commission_cents"] == round_half_up(
            1_275_000 * 0.25
        )
        assert engagement["final_commission_cents"] is None
        assert engagement["recording_fee_cents"] == 350_000

    def test_delivery_writes_the_final_figure_without_disturbing_the_provisional_one(
        self, api, agent_headers
    ):
        """Delivery adds the buy-out fee to the commissionable base, and the gap is the recording fee at the pinned rate.

        PRD: Same engagement, same pinned rate, but a strictly larger result than the provisional figure whenever `recording_fee_cents` is positive; the difference — `recording_fee_cents` multiplied by `commission_pct_snapshot`, rounded half up — is exactly the extra amount the remittance withholds beyond the provisional figure.
        Design: Difficulty/dual_variant_calc/dual_variant_commission_provisional_versus_final_same_engagement
        """
        bundle = setup_delivered_engagement(
            api,
            contract_overrides=RECORDING_CONTRACT,
            option_overrides=BUY_OUT_OPTION,
        )
        engagement = bundle["engagement"]

        assert engagement["booking_status"] == "DELIVERED"
        assert engagement["final_commission_cents"] == 406_250
        assert engagement["final_commission_cents"] == round_half_up(
            (1_275_000 + 350_000) * 0.25
        )
        assert engagement["provisional_commission_cents"] == 318_750
        delta = (
            engagement["final_commission_cents"]
            - engagement["provisional_commission_cents"]
        )
        assert delta == 87_500
        assert delta == round_half_up(350_000 * 0.25)

        remittance = bundle["remittance"]
        assert remittance["gross_fee_cents"] == 1_625_000
        assert remittance["commission_cents"] == 406_250
        assert_remittance_nets_out(remittance)

    def test_the_two_variants_read_the_same_snapshot_rate(self, api):
        """Both variants multiply by the rate pinned at execution rather than re-reading the roster.

        PRD: `commission_pct_snapshot` is pinned from the speaker's `default_commission_pct` **as it stands at this instant** and is never re-read from the speaker afterwards, so a later tier move does not re-price this engagement.
        Design: Difficulty/dual_variant_calc/dual_variant_commission_provisional_versus_final_same_engagement
        """
        bundle = setup_delivered_engagement(
            api,
            contract_overrides=RECORDING_CONTRACT,
            option_overrides=BUY_OUT_OPTION,
        )
        engagement = read_engagement(api, bundle["engagement"]["id"])
        snapshot = engagement["commission_pct_snapshot"]

        assert snapshot == pytest.approx(0.25, abs=0.001)
        assert engagement["provisional_commission_cents"] == round_half_up(
            engagement["quoted_fee_cents"] * snapshot
        )
        assert engagement["final_commission_cents"] == round_half_up(
            (engagement["quoted_fee_cents"] + engagement["recording_fee_cents"])
            * snapshot
        )


class TestRollingVersusLifetimeScore:
    def test_rolling_variant_renormalises_the_recency_weights_over_two_feedbacks(
        self, api, agent_headers
    ):
        """With only two feedbacks the recency weights become 0.625 and 0.375.

        PRD: Renormalisation matters below three feedbacks: with exactly two candidates the weights are 0.5 divided by 0.8, which is 0.625, and 0.3 divided by 0.8, which is 0.375 — not 0.5 and 0.3.
        Design: Difficulty/dual_variant_calc/dual_variant_speaker_score_rolling_versus_lifetime_diverge
        """
        bundle = setup_two_delivered_engagements(
            api,
            first_feedback={"content_score": 5, "logistics_score": 4},
            second_feedback={"content_score": 4, "logistics_score": 3},
            contract_overrides={
                "travel_policy_code": "POLICY_B",
                "recording_rights": "NONE",
            },
        )

        assert bundle["feedback"]["composite_score"] == pytest.approx(4.60, abs=0.01)
        assert bundle["feedback_2"]["composite_score"] == pytest.approx(3.60, abs=0.01)

        rolling = validate_success(
            api.get_speaker_performance(
                bundle["speaker"]["id"], agent_headers, params={"variant": "ROLLING"}
            )
        )
        assert rolling["variant"] == "ROLLING"
        assert rolling["score"] == pytest.approx(3.98, abs=0.01)
        assert rolling["feedback_count"] == 2

    def test_lifetime_variant_reads_the_same_rows_with_equal_weight_and_diverges(
        self, api, agent_headers
    ):
        """The flat mean over the identical rows lands above the recency-weighted figure, and only the rolling figure gates the tier.

        PRD: `lifetime_score` is the equal-weight arithmetic mean of `composite_score` across **all** candidates, rounded half up to two decimal places.
        Design: Difficulty/dual_variant_calc/dual_variant_speaker_score_rolling_versus_lifetime_diverge
        """
        bundle = setup_two_delivered_engagements(
            api,
            first_feedback={"content_score": 5, "logistics_score": 4},
            second_feedback={"content_score": 4, "logistics_score": 3},
            contract_overrides={
                "travel_policy_code": "POLICY_B",
                "recording_rights": "NONE",
            },
        )

        lifetime = validate_success(
            api.get_speaker_performance(
                bundle["speaker"]["id"], agent_headers, params={"variant": "LIFETIME"}
            )
        )
        assert lifetime["variant"] == "LIFETIME"
        assert lifetime["score"] == pytest.approx(4.10, abs=0.01)
        assert lifetime["feedback_count"] == 2

        speaker = read_speaker(api, bundle["speaker"]["id"])
        assert speaker["rolling_score"] == pytest.approx(3.98, abs=0.01)
        assert speaker["lifetime_score"] == pytest.approx(4.10, abs=0.01)
        assert speaker["engagements_delivered_count"] == 2

    def test_the_tier_gate_reads_the_rolling_figure_only(self, api, agent_headers):
        """A lifetime mean above the silver gate does not promote a speaker whose rolling figure sits below it.

        PRD: The gate reads the rolling figure only — never the lifetime one — and it compares against the already-rounded two-decimal value.
        Design: Difficulty/dual_variant_calc/dual_variant_speaker_score_rolling_versus_lifetime_diverge
        """
        bundle = setup_two_delivered_engagements(
            api,
            first_feedback={"content_score": 5, "logistics_score": 4},
            second_feedback={"content_score": 4, "logistics_score": 3},
            contract_overrides={
                "travel_policy_code": "POLICY_B",
                "recording_rights": "NONE",
            },
        )
        speaker = read_speaker(api, bundle["speaker"]["id"])

        assert speaker["lifetime_score"] == pytest.approx(4.10, abs=0.01)
        assert speaker["rolling_score"] == pytest.approx(3.98, abs=0.01)
        assert speaker["roster_tier"] == "BRONZE"
        assert speaker["default_commission_pct"] == pytest.approx(0.25, abs=0.001)
        assert speaker["feedback_count"] == 2
