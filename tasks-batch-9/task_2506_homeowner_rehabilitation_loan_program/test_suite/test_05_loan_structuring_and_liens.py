"""Structuring the note: the financed recording fee and the lien gates."""

import pytest

from test_helpers import (
    api_client,
    assert_program_year_ledger_conserved,
    assert_rehab_loan,
    assert_two_axes,
    assert_unset,
    record_lien_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    LOAN_OFFICER,
    clear_historic_review,
    clear_lead_review,
    refresh_application,
    refresh_loan,
    refresh_program_year,
    setup_case,
    setup_historic_case,
    structure_loan,
)

# The three-line historic scope: a lead line, a historic line and a plain line.
LEAD_LINE = {
    "description": "Window sash lead hazard reduction",
    "category": "LEAD_HAZARD_CONTROL",
    "priority_class": "HEALTH_SAFETY",
    "estimated_cost_cents": 1_234_567,
    "is_lead_hazard_reduction": True,
    "is_historic_sensitive": False,
}
HISTORIC_LINE = {
    "description": "Character-defining porch column repair",
    "category": "STRUCTURAL",
    "priority_class": "CODE",
    "estimated_cost_cents": 987_654,
    "is_lead_hazard_reduction": False,
    "is_historic_sensitive": True,
}
PLAIN_LINE = {
    "description": "Kitchen cabinet replacement",
    "category": "ACCESSIBILITY",
    "priority_class": "GENERAL_PROPERTY_IMPROVEMENT",
    "estimated_cost_cents": 500_001,
    "is_lead_hazard_reduction": False,
    "is_historic_sensitive": False,
}


class TestFinancedRecordingFee:
    """The fee is financed into the principal but chosen from the pre-fee cost."""

    def test_a_project_cost_at_the_first_tier_ceiling_carries_the_lowest_fee(self):
        """A 2,000,000 project cost sits on the tier edge and takes the 15,000 fee.

        PRD: "`lien_recording_fee_cents` is chosen once from the pre-fee project
        cost: a project cost at or below twenty thousand dollars — 2,000,000
        cents — carries a fee of one hundred and fifty dollars, or 15,000 cents;
        a project cost above that and at or below fifty thousand dollars —
        5,000,000 cents — carries a fee of two hundred and fifty dollars, or
        25,000 cents; a project cost above fifty thousand dollars carries a fee
        of four hundred dollars, or 40,000 cents."

        Design: Difficulty/combinatorial_formula/loan_recording_fee_tier_is_keyed_to_the_pre_fee_project_cost
        """
        case = setup_case(stage="awarded", bid_amount_cents=2_000_000)

        loan = structure_loan(case["application"]["id"])

        assert_rehab_loan(loan)
        assert loan["awarded_bid_amount_cents"] == 2_000_000
        assert loan["approved_project_cost_cents"] == 2_000_000
        assert loan["lien_recording_fee_cents"] == 15_000, (
            "A pre-fee project cost of exactly 2,000,000 stays in the lowest fee "
            f"tier, got {loan['lien_recording_fee_cents']}"
        )
        assert loan["principal_cents"] == 2_015_000
        assert loan["monthly_payment_cents"] == 0
        assert loan["status"] == "STRUCTURED"

    def test_the_fee_is_not_re_chosen_from_the_principal_it_was_added_to(self):
        """Financing the fee must not push the same loan into the next fee tier.

        PRD: "That tier is locked at structuring: the fee is never re-chosen
        after it has been added into the principal, is never re-chosen because
        the per-household cap bound the principal, and is never re-chosen when a
        change order later moves the project cost."

        Design: Difficulty/combinatorial_formula/loan_recording_fee_tier_is_keyed_to_the_pre_fee_project_cost
        """
        case = setup_case(stage="awarded", bid_amount_cents=2_000_000)

        loan = structure_loan(case["application"]["id"])

        assert loan["lien_recording_fee_cents"] != 25_000, (
            "A 2,015,000 principal would fall in the second fee tier, but the "
            "tier is read from the 2,000,000 pre-fee cost"
        )
        assert loan["principal_cents"] != 2_025_000, (
            "2,025,000 is the figure produced by re-deriving the fee from the "
            "post-fee principal"
        )
        assert loan["principal_cents"] == loan["approved_project_cost_cents"] + 15_000

    def test_one_cent_above_the_tier_ceiling_carries_the_second_tier_fee(self):
        """The tier edge is inclusive below and exclusive above.

        PRD: "`lien_recording_fee_cents` is chosen once from the pre-fee project
        cost: a project cost at or below twenty thousand dollars — 2,000,000
        cents — carries a fee of one hundred and fifty dollars, or 15,000 cents;
        a project cost above that and at or below fifty thousand dollars —
        5,000,000 cents — carries a fee of two hundred and fifty dollars, or
        25,000 cents; a project cost above fifty thousand dollars carries a fee
        of four hundred dollars, or 40,000 cents."

        Design: Difficulty/combinatorial_formula/loan_recording_fee_tier_is_keyed_to_the_pre_fee_project_cost
        """
        case = setup_case(stage="awarded", bid_amount_cents=2_000_001)

        loan = structure_loan(case["application"]["id"])

        assert loan["approved_project_cost_cents"] == 2_000_001
        assert loan["lien_recording_fee_cents"] == 25_000, (
            "One cent above the tier ceiling moves the fee to 25,000, got "
            f"{loan['lien_recording_fee_cents']}"
        )
        assert loan["principal_cents"] == 2_025_001

    def test_a_newly_structured_note_commits_nothing_and_leaves_the_lien_unset(self):
        """Structuring is a paper act: no money moves and no lien exists yet.

        PRD: "A newly structured note opens in `STRUCTURED` and commits nothing
        to the program year."

        PRD: "`lien_position`, `lien_recorded_at` and `forgiveness_start_date`
        are unset; `contract_earned_cents`, `disbursed_cents`,
        `retainage_held_cents`, `forgiven_cents` and `principal_repaid_cents`
        are zero; `unforgiven_balance_cents` is the principal less accrued
        forgiveness less principal repaid, which at this point equals the full
        principal; and `recapture_event_type`, `recapture_event_date`,
        `net_proceeds_cents`, `recapture_amount_cents`,
        `shortfall_forgiven_cents` and `program_income_posted_cents` are all
        unset."

        Design: Difficulty/combinatorial_formula/loan_recording_fee_tier_is_keyed_to_the_pre_fee_project_cost
        """
        case = setup_case(stage="awarded", bid_amount_cents=2_000_000)

        loan = structure_loan(case["application"]["id"])

        for field in ("lien_position", "lien_recorded_at", "forgiveness_start_date"):
            assert_unset(loan, field)
        for field in (
            "contract_earned_cents",
            "disbursed_cents",
            "retainage_held_cents",
            "forgiven_cents",
            "principal_repaid_cents",
        ):
            assert loan[field] == 0, f"{field} should open at zero, got {loan[field]}"
        assert loan["unforgiven_balance_cents"] == loan["principal_cents"]
        program_year = refresh_program_year(case["program_year"]["id"])
        assert program_year["committed_amount_cents"] == 0, (
            "Structuring commits nothing, got "
            f"{program_year['committed_amount_cents']}"
        )
        assert program_year["uncommitted_amount_cents"] == 50_000_000
        assert_program_year_ledger_conserved(program_year)


class TestLienRecordingComplianceGate:
    """A valid note cannot record its lien while the case sits on two holds."""

    @pytest.fixture
    def dual_hold_loan(self):
        """A 1962 historic case with a structured 3,225,000 note and both holds open."""
        return setup_historic_case(
            stage="structured",
            clear_compliance=False,
            lines=[LEAD_LINE, HISTORIC_LINE, PLAIN_LINE],
            bid_amount_cents=3_200_000,
        )

    def _attempt_recording(self, loan_id):
        return api_client.record_lien(
            loan_id,
            record_lien_payload(
                lien_position=2, recorded_instrument_number="INS-2026-0C1"
            ),
            LOAN_OFFICER,
        )

    def test_the_first_recording_attempt_answers_the_lead_clearance(
        self, dual_hold_loan
    ):
        """Both axes are open, and the lead axis is reported first.

        PRD: "Recording proceeds only from a note in `STRUCTURED`, only from a
        compliance posture of `CLEAR` or `CLEARED_WITH_PROTOCOL` — with the two
        clearance identifiers of §3.4 guarding the other postures — and only when
        the program year's `uncommitted_amount_cents` is at least the note's
        `principal_cents`; an insufficient balance is refused with
        `ERR_ALLOCATION_INSUFFICIENT`."

        Design: Difficulty/cross_entity_state_dependency/lien_recording_is_gated_by_the_applications_compliance_posture
        """
        loan = dual_hold_loan["loan"]
        assert loan["principal_cents"] == 3_225_000, (
            "A 3,200,000 contract in the second fee tier structures to 3,225,000, "
            f"got {loan['principal_cents']}"
        )
        assert_two_axes(dual_hold_loan["application"], "AWARDED", "DUAL_HOLD")

        response = self._attempt_recording(loan["id"])

        validate_error(response, "ERR_LEAD_CLEARANCE_REQUIRED")
        unchanged = refresh_loan(loan["id"])
        assert unchanged["status"] == "STRUCTURED"
        assert_unset(unchanged, "lien_recorded_at")
        assert (
            refresh_program_year(dual_hold_loan["program_year"]["id"])[
                "committed_amount_cents"
            ]
            == 0
        )

    def test_the_second_attempt_answers_the_historic_clearance(self, dual_hold_loan):
        """Discharging lead exposes the historic hold underneath it.

        PRD: "From `DUAL_HOLD`, a completed risk assessment moves the posture
        `DUAL_HOLD → HISTORIC_HOLD`, leaving the historic axis outstanding; this
        path additionally requires that the case's `workflow_state` be one of
        `INSPECTED`, `WRITEUP_APPROVED`, `BID_OPEN`, `BID_FAILED` or
        `AWARDED`."

        Design: Difficulty/cross_entity_state_dependency/lien_recording_is_gated_by_the_applications_compliance_posture
        """
        loan_id = dual_hold_loan["loan"]["id"]
        application_id = dual_hold_loan["application"]["id"]
        validate_error(
            self._attempt_recording(loan_id), "ERR_LEAD_CLEARANCE_REQUIRED"
        )

        cleared = clear_lead_review(application_id, hazard_control_method="ABATEMENT")

        assert cleared["compliance_posture"] == "HISTORIC_HOLD"
        assert cleared["lead_hazard_control_method"] == "ABATEMENT"
        response = self._attempt_recording(loan_id)
        validate_error(response, "ERR_HISTORIC_CLEARANCE_REQUIRED")
        assert refresh_loan(loan_id)["status"] == "STRUCTURED"

    def test_the_third_attempt_records_the_lien_and_commits_the_money(
        self, dual_hold_loan
    ):
        """Once both axes clear, the identical request records the mortgage.

        PRD: "The program year's `committed_amount_cents` increases by the full
        `principal_cents`. The recording fee is then disbursed immediately: the
        note's `disbursed_cents` increases by `lien_recording_fee_cents`, the
        program year's `committed_amount_cents` decreases by that same fee, and
        its `disbursed_amount_cents` increases by that same fee — so the fee
        passes straight through the committed bucket into the disbursed bucket in
        one step."

        Design: Difficulty/cross_entity_state_dependency/lien_recording_is_gated_by_the_applications_compliance_posture
        """
        loan_id = dual_hold_loan["loan"]["id"]
        application_id = dual_hold_loan["application"]["id"]
        validate_error(
            self._attempt_recording(loan_id), "ERR_LEAD_CLEARANCE_REQUIRED"
        )
        clear_lead_review(application_id, hazard_control_method="ABATEMENT")
        validate_error(
            self._attempt_recording(loan_id), "ERR_HISTORIC_CLEARANCE_REQUIRED"
        )
        cleared = clear_historic_review(
            application_id, shpo_review_outcome="NO_ADVERSE_EFFECT"
        )
        assert cleared["compliance_posture"] == "CLEARED_WITH_PROTOCOL"
        assert cleared["shpo_review_outcome"] == "NO_ADVERSE_EFFECT"

        recorded = validate_success(self._attempt_recording(loan_id), 200)

        assert recorded["status"] == "LIEN_RECORDED"
        assert recorded["lien_position"] == 2
        assert recorded["lien_recorded_at"] is not None
        assert recorded["principal_cents"] == 3_225_000
        assert recorded["disbursed_cents"] == 25_000, (
            "The financed recording fee is disbursed at recording, got "
            f"{recorded['disbursed_cents']}"
        )
        assert_two_axes(refresh_application(application_id), "UNDER_CONSTRUCTION")
        program_year = refresh_program_year(dual_hold_loan["program_year"]["id"])
        assert program_year["committed_amount_cents"] == 3_200_000
        assert program_year["disbursed_amount_cents"] == 25_000
        assert program_year["uncommitted_amount_cents"] == 46_775_000
        assert_program_year_ledger_conserved(program_year)
