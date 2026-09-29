"""Formulas whose intermediate order is observable in the output.

Both of these calculations would be easy to get almost right: the fee by summing
before rounding, the scorecard by re-deriving the penalty from the grade it just
produced. The PRD pins both orders and both mistakes are visible to the cent.
"""

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers.fixtures import HieHarness


class TestPerTierRoundingOrder:
    """Each tier charge is rounded before any addition happens."""

    def test_thirty_thousand_and_one_units_bill_49877_not_49876(self, hie: HieHarness):
        """The half-cent in each tier survives into the total.

        PRD 3.9: "Each tier's charge is computed as its quantity multiplied by its
        rate and **individually rounded half up to a whole cent**; only then are the
        three rounded charges added to give `volume_fee_cents`. Summing the
        unrounded tier charges and rounding once at the end is wrong."

        Design: Difficulty/combinatorial_formula/participation_fee_rounds_each_tier_before_summing_yielding_49877
        """
        participant = hie.participant_in_conformance_testing(
            legal_name="Straddle Valley Health",
            declared_annual_patient_volume=360012,
            primary_contact_email="billing@straddle.example",
        )
        invoice = hie.issue_invoice(
            participant["id"],
            billing_period_start="2026-06-01T00:00:00Z",
            billing_period_end="2026-07-01T00:00:00Z",
            basis_variant="PROVISIONAL",
            due_date="2026-08-15T00:00:00Z",
        )

        assert invoice["billable_volume_units"] == 30001
        assert invoice["tier_charge_breakdown"]["TIER_1"] == 43313
        assert invoice["tier_charge_breakdown"]["TIER_2"] == 6564
        assert invoice["tier_charge_breakdown"]["TIER_3"] == 0
        assert invoice["volume_fee_cents"] == 49877
        assert invoice["volume_fee_cents"] != 49876

    def test_the_flat_base_fee_and_forced_multiplier_complete_the_provisional_total(
        self, hie: HieHarness
    ):
        """The base fee is added before the single final multiplication and rounding.

        PRD 3.9: "A flat `base_platform_fee_cents` of 250,000 cents is added to
        `volume_fee_cents`, and the sum is multiplied by the applicable
        `quality_multiplier`; that product is rounded half up to a whole cent
        **exactly once** to give `total_cents`."

        Design: Difficulty/combinatorial_formula/participation_fee_rounds_each_tier_before_summing_yielding_49877
        """
        participant = hie.participant_in_conformance_testing(
            legal_name="Straddle Valley Health",
            declared_annual_patient_volume=360012,
            primary_contact_email="billing@straddle.example",
        )
        invoice = hie.issue_invoice(
            participant["id"],
            billing_period_start="2026-06-01T00:00:00Z",
            billing_period_end="2026-07-01T00:00:00Z",
            basis_variant="PROVISIONAL",
            due_date="2026-08-15T00:00:00Z",
        )

        assert invoice["base_platform_fee_cents"] == 250000
        assert invoice["quality_grade_snapshot"] == "UNGRADED"
        assert invoice["quality_multiplier"] == pytest.approx(1.00, abs=0.01)
        assert invoice["total_cents"] == 299877

        refreshed = hie.get_participant(participant["id"])
        assert refreshed["fee_tier"] == "TIER_2"
        assert refreshed["outstanding_balance_cents"] == 299877


class TestPenaltyKeyedToProvisionalGrade:
    """The penalty is read from the provisional grade and never recomputed."""

    SAMPLE = {
        "period_start": "2026-06-01T00:00:00Z",
        "period_end": "2026-07-01T00:00:00Z",
        "messages_received": 10000,
        "messages_rejected": 600,
        "required_fields_missing_count": 900,
        "duplicate_count": 600,
        "timeliness_p95_seconds": 1200,
    }

    def test_base_84_60_deducts_one_point_for_83_60_and_a_final_grade_of_c(
        self, hie: HieHarness
    ):
        """A B-grade base score lands in C only because the B penalty was applied.

        PRD 3.9: "The penalty is keyed on the provisional grade and is **never**
        recomputed from the final grade. Worked through: a `base_quality_score` of
        84.60 yields a `provisional_grade` of `B`, hence one penalty point, hence a
        `quality_score` of 83.60, hence a final `grade` of `C`. Re-deriving the
        penalty from that final `C` would deduct three points for 81.60 and is
        wrong."

        Design: Difficulty/combinatorial_formula/quality_score_penalty_keyed_to_provisional_grade_yields_83_60
        """
        participant = hie.participant_in_conformance_testing(
            legal_name="Midline Community Clinic",
            org_type="CLINIC",
            declared_annual_patient_volume=90000,
            primary_contact_email="quality@midline.example",
        )
        feed = hie.provision_feed(participant["id"], feed_type="CCDA")
        hie.record_sample(feed["id"], **self.SAMPLE)

        scorecard = hie.get_scorecard(participant["id"])
        assert scorecard["base_quality_score"] == pytest.approx(84.60, abs=0.01)
        assert scorecard["provisional_grade"] == "B"
        assert scorecard["penalty_points"] == 1
        assert scorecard["quality_score"] == pytest.approx(83.60, abs=0.01)
        assert scorecard["quality_score"] != pytest.approx(81.60, abs=0.01)
        assert scorecard["grade"] == "C"

        refreshed = hie.get_participant(participant["id"])
        assert refreshed["quality_score"] == pytest.approx(83.60, abs=0.01)
        assert refreshed["quality_grade"] == "C"

    def test_the_four_components_and_the_degradation_they_reveal(self, hie: HieHarness):
        """The blend that produces 84.60, and the feed state the same sample drives.

        PRD 3.9: "`base_quality_score` is the weighted blend of those four
        components — thirty hundredths of `completeness_component`, plus thirty
        hundredths of `rejection_component`, plus fifteen hundredths of
        `duplicate_component`, plus twenty-five hundredths of
        `timeliness_component` — rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/quality_score_penalty_keyed_to_provisional_grade_yields_83_60
        """
        participant = hie.participant_in_conformance_testing(
            legal_name="Midline Community Clinic",
            org_type="CLINIC",
            declared_annual_patient_volume=90000,
            primary_contact_email="quality@midline.example",
        )
        feed = hie.provision_feed(participant["id"], feed_type="CCDA")
        sample = hie.record_sample(feed["id"], **self.SAMPLE)
        assert sample["reject_rate"] == pytest.approx(0.0600, abs=0.0001)

        scorecard = hie.get_scorecard(participant["id"])
        assert scorecard["completeness_component"] == pytest.approx(91, abs=0.01)
        assert scorecard["rejection_component"] == pytest.approx(94, abs=0.01)
        assert scorecard["duplicate_component"] == pytest.approx(94, abs=0.01)
        assert scorecard["timeliness_component"] == pytest.approx(60, abs=0.01)
        assert scorecard["average_p95_seconds"] == pytest.approx(1200, abs=0.01)
        assert scorecard["samples_counted"] == 1

        refreshed_feed = validate_success(
            hie.client.get_data_feed(hie.admin, feed["id"]), 200
        )
        assert refreshed_feed["status"] == "DEGRADED"
        assert refreshed_feed["latest_reject_rate"] == pytest.approx(0.0600, abs=0.0001)
        assert refreshed_feed["sample_count"] == 1
