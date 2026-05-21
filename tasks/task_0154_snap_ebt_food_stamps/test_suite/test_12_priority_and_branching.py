"""Priority-pair validation conflicts and non-linear state-machine shapes.

Covers PRD §2.12 (validation priority) and §3.3, §3.7 (state branching/cyclic).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    NON_EXISTENT_UUID,
    ERR_INVALID_STATE, ERR_CARD_NOT_ACTIVE, ERR_INSUFFICIENT_FUNDS,
    ERR_FRAUD_HOLD,
    TEST_USERS, make_household_head_headers, make_merchant_headers,
    create_household, add_member, dob_for_age,
    setup_basic_household, setup_approved_household_with_active_card,
    setup_full_purchase_scene,
    create_draft_application, walk_to_interview_done,
    create_transaction_payload,
)


CASEWORKER = TEST_USERS["caseworker_headers"]
FRAUD_INV = TEST_USERS["fraud_investigator_headers"]


class TestApplicationBranchingWithRevert:
    def test_full_revert_resubmit_cycle(self, api):
        """PRD §3.3: "returning the application for correction reverts it from
        `SUBMITTED` back to `DRAFT`: `submitted_at` is cleared back to null."

        Claim (branching with revert): A workflow DRAFT -> SUBMITTED ->
        return-for-correction -> DRAFT -> SUBMITTED -> ... -> APPROVED
        exercises the revert branch and the canonical forward path.
        """
        # difficulty: non_linear_state_machine/application_branching_with_revert
        hh, _ = setup_basic_household(size=1, age=30)
        app = create_draft_application(hh["id"])
        # Forward: DRAFT -> SUBMITTED
        validate_success(api.submit_application(hh["id"], app["id"], CASEWORKER))
        # Revert: SUBMITTED -> DRAFT
        rev = validate_success(api.return_for_correction(hh["id"], app["id"], CASEWORKER))
        assert rev["state"] == "DRAFT"
        assert rev["submitted_at"] is None
        # Re-submit + interview + approve
        validate_success(api.submit_application(hh["id"], app["id"], CASEWORKER))
        validate_success(api.schedule_interview(hh["id"], app["id"], CASEWORKER))
        validate_success(api.complete_interview(hh["id"], app["id"], CASEWORKER))
        approved = validate_success(api.approve_application(hh["id"], app["id"], CASEWORKER))
        assert approved["state"] == "APPROVED"


class TestPriorityPairCardNotActiveBeatsFunds:
    def test_state_check_beats_balance_check(self, api):
        """PRD §3.5: "If the `EbtCard.status` is not `ACTIVE`, the transaction
        is declined with `decline_reason` = `CARD_NOT_ACTIVE` and the response
        is `ERR_CARD_NOT_ACTIVE`."

        Claim (priority): SUSPENDED card + huge requested amount yields
        ERR_CARD_NOT_ACTIVE (state check fires first).
        """
        # difficulty: priority_pair_validation_conflict/state_beats_fiscal_on_transaction
        ctx = setup_full_purchase_scene(size=1, age=30)
        validate_success(api.suspend_card(
            ctx["household"]["id"], ctx["card"]["id"], CASEWORKER
        ))
        m_headers = make_merchant_headers(ctx["merchant"]["id"])
        payload = create_transaction_payload(
            card_id=ctx["card"]["id"], merchant_id=ctx["merchant"]["id"],
            line_items=[{"item_category": "STAPLE", "unit_price_cents": 999999, "quantity": 1}],
        )
        resp = api.create_transaction(payload, m_headers)
        validate_error(resp, ERR_CARD_NOT_ACTIVE)
