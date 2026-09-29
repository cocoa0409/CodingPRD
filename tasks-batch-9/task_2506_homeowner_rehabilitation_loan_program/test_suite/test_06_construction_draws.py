"""Construction draws: the approval gate order and the payment cascade."""

import pytest

from test_helpers import (
    api_client,
    assert_construction_identity_conserved,
    assert_draw_request,
    assert_program_year_ledger_conserved,
    assert_unset,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    LOAN_OFFICER,
    approve_draw,
    build_draw_request,
    complete_draw_inspection,
    refresh_application,
    refresh_draw,
    refresh_loan,
    refresh_program_year,
)


class TestDrawApprovalGateOrder:
    """The sibling inspection row is tested before the contract balance."""

    @pytest.fixture
    def oversized_draw_case(self, lien_recorded_case):
        """A 2,500,000 draw on a 2,000,000 contract, so the fiscal gate is armed."""
        case = lien_recorded_case
        case["draw"] = build_draw_request(
            case["loan"]["id"],
            case["contractor"]["id"],
            requested_amount_cents=2_500_000,
            is_final_draw=False,
        )
        return case

    def test_a_failed_draw_inspection_answers_before_the_contract_balance(
        self, oversized_draw_case
    ):
        """One request breaks two rules and hears the inspection rule.

        PRD: "The addressed draw is in `INSPECTION_PASSED` — otherwise
        `ERR_DRAW_INSPECTION_NOT_PASSED` (409). Applies to approving a draw. A
        draw still in `SUBMITTED` (never inspected) or in `INSPECTION_FAILED`
        returns this identifier rather than the generic invalid-state identifier,
        because the gate is the state of the sibling inspection row rather than
        the draw itself."

        Design: Difficulty/priority_pair_validation_conflict/draw_approval_state_gate_outranks_the_contract_balance_gate
        """
        case = oversized_draw_case
        draw_id = case["draw"]["id"]
        complete_draw_inspection(
            case["application"]["id"], draw_id, result="FAIL", deficiency_count=2
        )
        assert refresh_draw(draw_id)["status"] == "INSPECTION_FAILED"

        response = api_client.approve_draw_request(draw_id, LOAN_OFFICER)

        validate_error(response, "ERR_DRAW_INSPECTION_NOT_PASSED")
        unchanged = refresh_draw(draw_id)
        assert unchanged["status"] == "INSPECTION_FAILED"
        assert_unset(unchanged, "approved_amount_cents")
        assert_unset(unchanged, "approved_by_user_id")
        loan = refresh_loan(case["loan"]["id"])
        assert loan["contract_earned_cents"] == 0
        assert loan["disbursed_cents"] == 15_000, (
            "Only the financed recording fee has been disbursed, got "
            f"{loan['disbursed_cents']}"
        )

    def test_a_never_inspected_draw_answers_the_same_inspection_gate(
        self, oversized_draw_case
    ):
        """A draw still awaiting its site visit is not an invalid-state refusal.

        PRD: "The draw must be in `INSPECTION_PASSED`: a draw still in
        `SUBMITTED`, never inspected, and a draw in `INSPECTION_FAILED` are both
        refused with `ERR_DRAW_INSPECTION_NOT_PASSED` rather than the generic
        invalid-state identifier, because the gate is the state of the sibling
        inspection row rather than the draw's own lifecycle."

        Design: Difficulty/priority_pair_validation_conflict/draw_approval_state_gate_outranks_the_contract_balance_gate
        """
        case = oversized_draw_case
        draw_id = case["draw"]["id"]
        assert_draw_request(case["draw"])
        assert case["draw"]["status"] == "SUBMITTED"

        response = api_client.approve_draw_request(draw_id, LOAN_OFFICER)

        validate_error(response, "ERR_DRAW_INSPECTION_NOT_PASSED")
        assert refresh_draw(draw_id)["status"] == "SUBMITTED"

    def test_the_contract_balance_gate_answers_once_the_inspection_passes(
        self, oversized_draw_case
    ):
        """Clearing the state gate exposes the fiscal gate underneath it.

        PRD: "And the draw must fit inside the construction contract:
        `requested_amount_cents` must be at or below the loan's
        `approved_project_cost_cents` less its `contract_earned_cents`, so a draw
        for exactly the remaining balance is allowed while anything larger is
        refused with `ERR_DRAW_EXCEEDS_CONTRACT_BALANCE`."

        Design: Difficulty/priority_pair_validation_conflict/draw_approval_state_gate_outranks_the_contract_balance_gate
        """
        case = oversized_draw_case
        draw_id = case["draw"]["id"]
        complete_draw_inspection(
            case["application"]["id"], draw_id, result="FAIL", deficiency_count=2
        )
        complete_draw_inspection(
            case["application"]["id"], draw_id, result="PASS", deficiency_count=0
        )
        assert refresh_draw(draw_id)["status"] == "INSPECTION_PASSED"

        response = api_client.approve_draw_request(draw_id, LOAN_OFFICER)

        validate_error(response, "ERR_DRAW_EXCEEDS_CONTRACT_BALANCE")
        unchanged = refresh_draw(draw_id)
        assert unchanged["status"] == "INSPECTION_PASSED"
        assert_unset(unchanged, "approved_amount_cents")


class TestPaymentCascade:
    """One payment call moves a draw, a note, a program year and a case."""

    @pytest.fixture
    def approved_final_draw_case(self, lien_recorded_case):
        """A 2,000,000 final draw, inspected and approved, waiting to be paid."""
        case = lien_recorded_case
        draw = build_draw_request(
            case["loan"]["id"],
            case["contractor"]["id"],
            requested_amount_cents=2_000_000,
            is_final_draw=True,
        )
        complete_draw_inspection(case["application"]["id"], draw["id"])
        case["draw"] = approve_draw(draw["id"])
        return case

    def test_paying_the_final_draw_posts_the_money_on_the_note(
        self, approved_final_draw_case
    ):
        """The first hop pays the draw and moves the loan ledger.

        PRD: "Hop one moves the draw `APPROVED → PAID`, stamps `paid_at` from the
        logical clock, and posts the money on the loan: `contract_earned_cents`
        increases by `approved_amount_cents`, `retainage_held_cents` increases by
        `retainage_cents` on an ordinary draw or is released to zero on a final
        draw, and `disbursed_cents` increases by `net_payment_cents`."

        Design: Difficulty/transitive_cascade/draw_payment_cascades_four_hops_to_construction_complete
        """
        case = approved_final_draw_case
        draw = case["draw"]
        assert draw["approved_amount_cents"] == 2_000_000
        assert draw["retainage_cents"] == 0, (
            "A final draw withholds no new retainage, got "
            f"{draw['retainage_cents']}"
        )
        assert draw["net_payment_cents"] == 2_000_000

        paid = validate_success(api_client.pay_draw_request(draw["id"], LOAN_OFFICER), 200)

        assert paid["status"] == "PAID"
        assert paid["paid_at"] is not None
        loan = refresh_loan(case["loan"]["id"])
        assert loan["contract_earned_cents"] == 2_000_000
        assert loan["retainage_held_cents"] == 0
        assert loan["disbursed_cents"] == 2_015_000, (
            "The 2,000,000 net payment lands on top of the 15,000 recording fee, "
            f"got {loan['disbursed_cents']}"
        )
        assert_construction_identity_conserved(loan)

    def test_the_payment_re_points_the_program_year_buckets(
        self, approved_final_draw_case
    ):
        """The second hop moves the same money between the program year buckets.

        PRD: "Hop two posts the same money on the program year:
        `committed_amount_cents` decreases by `net_payment_cents` and
        `disbursed_amount_cents` increases by the same figure."

        Design: Difficulty/transitive_cascade/draw_payment_cascades_four_hops_to_construction_complete
        """
        case = approved_final_draw_case
        before = refresh_program_year(case["program_year"]["id"])
        assert before["committed_amount_cents"] == 2_000_000
        assert before["disbursed_amount_cents"] == 15_000

        validate_success(
            api_client.pay_draw_request(case["draw"]["id"], LOAN_OFFICER), 200
        )

        after = refresh_program_year(case["program_year"]["id"])
        assert after["committed_amount_cents"] == 0
        assert after["disbursed_amount_cents"] == 2_015_000
        assert after["uncommitted_amount_cents"] == 47_985_000
        assert_program_year_ledger_conserved(after)

    def test_the_last_cent_drives_the_note_and_the_case_forward(
        self, approved_final_draw_case
    ):
        """The third and fourth hops fire only because the note is fully drawn.

        PRD: "Hop three moves the loan: a first payment takes it `LIEN_RECORDED →
        DISBURSING`, and once the posted payment has brought `disbursed_cents` to
        equal `principal_cents` exactly, the loan moves `DISBURSING →
        FULLY_DISBURSED`. Hop four follows only that second loan transition,
        driving the case `UNDER_CONSTRUCTION → CONSTRUCTION_COMPLETE`."

        Design: Difficulty/transitive_cascade/draw_payment_cascades_four_hops_to_construction_complete
        """
        case = approved_final_draw_case
        assert refresh_loan(case["loan"]["id"])["status"] == "LIEN_RECORDED"
        assert (
            refresh_application(case["application"]["id"])["workflow_state"]
            == "UNDER_CONSTRUCTION"
        )

        validate_success(
            api_client.pay_draw_request(case["draw"]["id"], LOAN_OFFICER), 200
        )

        loan = refresh_loan(case["loan"]["id"])
        assert loan["disbursed_cents"] == loan["principal_cents"]
        assert loan["status"] == "FULLY_DISBURSED", (
            "Bringing disbursed_cents up to principal_cents fully disburses the "
            f"note, got {loan['status']}"
        )
        assert loan["status"] != "SERVICING", (
            "Servicing begins at close-out, which is a separate request"
        )
        assert (
            refresh_application(case["application"]["id"])["workflow_state"]
            == "CONSTRUCTION_COMPLETE"
        )
