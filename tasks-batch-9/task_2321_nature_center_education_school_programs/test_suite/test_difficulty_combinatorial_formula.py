"""Depth tests for the three multi-step formulas whose evaluation order the PRD pins:
the per-student rounding point in fee assessment (PRD §3.8), the contribution floor and
bucket order in the award waterfall (PRD §3.8), and the four-factor learning gain index
(PRD §3.9).
"""

import pytest

from test_helpers import (
    DEFAULT_ALIGNMENTS,
    assert_decimal_places,
    assert_fund_ledger_conserved,
    refresh_booking,
    refresh_fund,
    refresh_offering,
    setup_booking_scenario,
    setup_booking_with_approved_aid,
    setup_submitted_evaluation,
)

# The two-claim offering of the canonical scenario plus one more distinct pairing, so
# ``standard_alignment_count`` reaches three without repeating a code/dimension pair.
THREE_ALIGNMENTS = DEFAULT_ALIGNMENTS + (
    {"standard_code": "3-LS4-4", "dimension": "CROSSCUTTING_CONCEPT"},
)


class TestFeePerStudentRoundingBeforeMultiplication:
    """A 1233-cent list price at a 10 percent volume discount over 30 billable students:
    rounding the per-student price first gives a different total from rounding the product."""

    def test_discounted_per_student_price_is_rounded_before_multiplying(self):
        """PRD §3.8: "Step three applies the discount **per student and rounds before multiplying**: the offering's `base_fee_cents_per_student` is multiplied by one minus the discount fraction, that per-student amount is rounded half up to a whole cent, and only then is it multiplied by the billable headcount to give the programme fee."

        Design: Difficulty/combinatorial_formula/fee_per_student_rounding_before_multiplication
        """
        scenario = setup_booking_scenario(
            student_count=30, chaperone_count=3, assign_educator=False
        )
        booking = refresh_booking(scenario["booking"]["id"])

        assert scenario["offering"]["base_fee_cents_per_student"] == 1233
        assert booking["provisional_gross_fee_cents"] == 33300

    def test_multiplying_before_rounding_is_not_the_order_used(self):
        """PRD §3.8: "The alternative order — multiplying first and rounding the product — is explicitly not used, and the two orders differ by cents on realistic inputs."

        Design: Difficulty/combinatorial_formula/fee_per_student_rounding_before_multiplication
        """
        scenario = setup_booking_scenario(
            student_count=30, chaperone_count=3, assign_educator=False
        )
        booking = refresh_booking(scenario["booking"]["id"])

        assert booking["provisional_gross_fee_cents"] == 33300
        assert booking["provisional_gross_fee_cents"] != 33291

    def test_provisional_fee_initialises_net_due_alongside_required_chaperones(self):
        """PRD §3.6: "And `provisional_gross_fee_cents` is computed by the provisional variant of the fee assessment described in §3.8, with `net_due_cents` initialised to that provisional figure since no aid has been awarded yet."

        Design: Difficulty/combinatorial_formula/fee_per_student_rounding_before_multiplication
        """
        scenario = setup_booking_scenario(
            student_count=30, chaperone_count=3, assign_educator=False
        )
        booking = refresh_booking(scenario["booking"]["id"])

        assert booking["net_due_cents"] == 33300
        assert booking["required_chaperones"] == 3


class TestAidAwardPinnedOrderContributionFloorBeforeWaterfall:
    """A TIER_1 school on a 33300-cent gross fee for 30 planned students: the 4500-cent
    contribution floor caps the scholarship bucket before the transport bucket is filled."""

    def test_scholarship_ceiling_subtracts_the_contribution_floor_from_the_fee_basis(self):
        """PRD §3.8: "Step four takes the scholarship ceiling as the smallest of three quantities: the `requested_scholarship_cents`, the fee basis multiplied by the tier cap fraction and rounded half up to whole cents, and the fee basis less the contribution floor with a lower bound of zero."

        Design: Difficulty/combinatorial_formula/aid_award_pinned_order_contribution_floor_before_waterfall
        """
        scenario = setup_booking_with_approved_aid()
        aid = scenario["aid_application"]

        assert aid["requested_scholarship_cents"] == 33300
        assert aid["awarded_scholarship_cents"] == 28800

    def test_transport_bucket_takes_what_the_scholarship_bucket_left(self):
        """PRD §3.8: "The scholarship bucket fills first: `awarded_scholarship_cents` is the smaller of the scholarship ceiling and the budget, and that award is then subtracted from the budget."

        Design: Difficulty/combinatorial_formula/aid_award_pinned_order_contribution_floor_before_waterfall
        """
        scenario = setup_booking_with_approved_aid()
        aid = scenario["aid_application"]

        assert aid["awarded_scholarship_cents"] == 28800
        assert aid["awarded_transport_cents"] == 6500

    def test_partial_award_outcome_state_follows_the_awarded_versus_requested_totals(self):
        """PRD §3.8: "Step nine chooses the outcome state: the application transitions `SUBMITTED → APPROVED` when `awarded_scholarship_cents` equals `requested_scholarship_cents` **and** `awarded_transport_cents` equals `requested_transport_cents`, and `SUBMITTED → PARTIALLY_APPROVED` when the total awarded is less than the total requested but still greater than zero."

        Design: Difficulty/combinatorial_formula/aid_award_pinned_order_contribution_floor_before_waterfall
        """
        scenario = setup_booking_with_approved_aid()
        aid = scenario["aid_application"]

        assert aid["status"] == "PARTIALLY_APPROVED"

    def test_only_the_scholarship_credit_reduces_what_the_school_owes(self):
        """PRD §3.8: "Accordingly, `net_due_cents` is the `final_gross_fee_cents` less `aid_amount_cents` once the booking has been delivered and the `provisional_gross_fee_cents` less `aid_amount_cents` before that, in either case with a lower bound of zero."

        Design: Difficulty/combinatorial_formula/aid_award_pinned_order_contribution_floor_before_waterfall
        """
        scenario = setup_booking_with_approved_aid()
        booking = refresh_booking(scenario["booking"]["id"])

        assert booking["aid_amount_cents"] == 28800
        assert booking["transport_subsidy_cents"] == 6500
        assert booking["net_due_cents"] == 4500
        assert booking["funding_status"] == "AID_APPROVED"

    def test_pool_ledger_moves_with_the_awarded_totals(self):
        """PRD §3.8: "Either approval outcome advances the booking's `funding_status` from `AID_PENDING` to `AID_APPROVED` and recomputes the pool's `pending_cents`, `committed_cents`, `transport_awarded_cents` and `available_cents`."

        Design: Difficulty/combinatorial_formula/aid_award_pinned_order_contribution_floor_before_waterfall
        """
        scenario = setup_booking_with_approved_aid()
        fund = refresh_fund(scenario["fund"]["id"])

        assert fund["pending_cents"] == 0
        assert fund["committed_cents"] == 35300
        assert fund["available_cents"] == 4964700
        assert_fund_ledger_conserved(fund)


class TestLearningGainIndexNonlinearThreeFactor:
    """Normalised student gain, weighted teacher composite, delivery fidelity and the
    thin-alignment penalty combine multiplicatively, with a single rounding at the end."""

    REPORT_SCORES = {
        "teacher_score_standards_alignment": 5,
        "teacher_score_logistics": 4,
        "teacher_score_engagement": 4,
        "student_pre_score_avg": 8,
        "student_post_score_avg": 15,
    }

    def test_thin_alignment_penalty_lands_the_index_at_zero_point_six_four(self):
        """PRD §3.9: "Step five combines everything: six tenths of the normalised gain plus four tenths of the teacher composite, that sum multiplied by the fidelity factor and then by the alignment factor, the product clamped into the closed range 0 through 1, and finally rounded half up to two decimal places — the single rounding in the whole computation."

        Design: Difficulty/combinatorial_formula/learning_gain_index_nonlinear_three_factor
        """
        scenario = setup_submitted_evaluation(
            report_overrides=dict(self.REPORT_SCORES),
            actual_student_count=28,
            actual_chaperone_count=3,
        )
        report = scenario["evaluation_report"]

        assert report["learning_gain_index"] == pytest.approx(0.64, abs=0.01)
        assert_decimal_places(report["learning_gain_index"], 2, "learning_gain_index")

    def test_two_alignment_offering_does_not_earn_the_unpenalised_index(self):
        """PRD §3.9: "Step four applies a thin-alignment penalty keyed on the offering's standards coverage: the factor is 0.90 when the booked offering's `standard_alignment_count` is below 3 as it stands at submit time, and 1.00 otherwise."

        Design: Difficulty/combinatorial_formula/learning_gain_index_nonlinear_three_factor
        """
        scenario = setup_submitted_evaluation(
            report_overrides=dict(self.REPORT_SCORES),
            actual_student_count=28,
            actual_chaperone_count=3,
        )
        offering = refresh_offering(scenario["offering"]["id"])

        assert offering["standard_alignment_count"] == 2
        assert scenario["evaluation_report"]["learning_gain_index"] == pytest.approx(
            0.64, abs=0.01
        )
        assert scenario["evaluation_report"]["learning_gain_index"] != pytest.approx(
            0.71, abs=0.01
        )

    def test_three_alignment_offering_earns_the_unpenalised_index(self):
        """PRD §3.9: "Step four applies a thin-alignment penalty keyed on the offering's standards coverage: the factor is 0.90 when the booked offering's `standard_alignment_count` is below 3 as it stands at submit time, and 1.00 otherwise."

        Design: Difficulty/combinatorial_formula/learning_gain_index_nonlinear_three_factor
        """
        scenario = setup_submitted_evaluation(
            alignments=THREE_ALIGNMENTS,
            report_overrides=dict(self.REPORT_SCORES),
            actual_student_count=28,
            actual_chaperone_count=3,
        )
        offering = refresh_offering(scenario["offering"]["id"])

        assert offering["standard_alignment_count"] == 3
        assert scenario["evaluation_report"]["learning_gain_index"] == pytest.approx(
            0.71, abs=0.01
        )

    def test_submission_computes_the_index_and_advances_the_report(self):
        """PRD §3.9: "Submission advances `DRAFT → SUBMITTED` and requires the parent booking's `delivery_status` to be `DELIVERED`; it stamps `submitted_by_user_id` from `X-User-ID` and computes `learning_gain_index`."

        Design: Difficulty/combinatorial_formula/learning_gain_index_nonlinear_three_factor
        """
        scenario = setup_submitted_evaluation(
            report_overrides=dict(self.REPORT_SCORES),
            actual_student_count=28,
            actual_chaperone_count=3,
        )
        report = scenario["evaluation_report"]
        booking = refresh_booking(scenario["booking"]["id"])

        assert report["status"] == "SUBMITTED"
        assert booking["delivery_status"] == "DELIVERED"
        assert booking["rain_diverted_to_offering_id"] is None
        assert report["learning_gain_index"] == pytest.approx(0.64, abs=0.01)
