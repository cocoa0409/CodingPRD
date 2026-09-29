"""A deduction's claim dimension travels a whole round trip while its money stays open."""

import pytest

from test_helpers import (
    APPROVER_USER_ID,
    FILER_USER_ID,
    DeductionReasonCode,
    DeductionSettlementState,
    DisputeState,
    fixtures,
)
from test_helpers.assertions import (
    assert_deduction,
    assert_deduction_money_conserved,
    expected_shortage_recovery,
)

AMOUNT_CENTS = 90000
RECOVERABLE_CENTS = 45000


@pytest.fixture
def denied_claim(api):
    """A shortage claim that was filed, substantiated with two documents, and denied.

    Deductions need no active principal, so the principal here stays a prospect.
    """
    retailer = fixtures.create_retailer(api, deduction_dispute_window_days=90)
    principal = fixtures.create_principal(api)
    deduction = fixtures.substantiated_deduction(
        api,
        retailer["id"],
        principal["id"],
        amount_cents=AMOUNT_CENTS,
        reason_code=DeductionReasonCode.SHORTAGE,
        deduction_date="2026-08-01",
    )
    deduction = fixtures.deny_recovery(
        api, deduction["id"], "Shortage not evidenced at store level"
    )
    return {"retailer": retailer, "principal": principal, "deduction": deduction}


def refile_and_resubstantiate(api, deduction_id):
    fixtures.file_claim(api, deduction_id, AMOUNT_CENTS)
    return fixtures.substantiate_twice(
        api, deduction_id, ["POD-1001-REV", "SIGNED-BOL-3003"]
    )


class TestDeductionDualDimensions:
    def test_denial_leaves_the_money_dimension_untouched(self, api, denied_claim):
        """The claim reaches DENIED while the settlement dimension is still OPEN.

        PRD: "Denial is the mirror image and is deliberately money-neutral."

        Design: Difficulty/non_linear_state_machine/deduction_settlement_and_dispute_dimensions_advance_independently
        """
        deduction = fixtures.get_deduction(api, denied_claim["deduction"]["id"])

        assert_deduction(deduction)
        assert deduction["dispute_state"] == DisputeState.DENIED
        assert deduction["settlement_state"] == DeductionSettlementState.OPEN
        assert deduction["open_cents"] == AMOUNT_CENTS
        assert deduction["recovered_cents"] == 0
        assert deduction["conceded_cents"] == 0
        assert_deduction_money_conserved(deduction)

    def test_the_refile_resets_the_evidence_and_moves_no_money(self, api, denied_claim):
        """Refiling counts the round trip, clears the denial and drops the document count.

        PRD: "A refile increases `refile_count` by one, resets `substantiation_doc_count` to
        0 so evidence must be assembled afresh, clears `denial_reason` to null, and records
        the new `filed_by_user_id`."

        Design: Difficulty/non_linear_state_machine/deduction_settlement_and_dispute_dimensions_advance_independently
        """
        refiled = fixtures.file_claim(api, denied_claim["deduction"]["id"], AMOUNT_CENTS)

        assert refiled["dispute_state"] == DisputeState.FILED
        assert refiled["refile_count"] == 1
        assert refiled["substantiation_doc_count"] == 0
        assert refiled["denial_reason"] is None
        assert refiled["settlement_state"] == DeductionSettlementState.OPEN
        assert refiled["open_cents"] == AMOUNT_CENTS
        assert refiled["claim_amount_cents"] == AMOUNT_CENTS
        assert_deduction_money_conserved(refiled)

    def test_the_second_document_only_increments_the_counter(self, api, denied_claim):
        """The first document transitions the claim; the second is a pure self-loop.

        PRD: "Substantiation then attaches evidence one document at a time, each call
        carrying a `document_ref`: the first document moves `dispute_state` from `FILED` to
        `SUBSTANTIATED`, and further calls while already `SUBSTANTIATED` are a self-loop that
        only increments `substantiation_doc_count` without changing state."

        Design: Difficulty/non_linear_state_machine/deduction_settlement_and_dispute_dimensions_advance_independently
        """
        deduction_id = denied_claim["deduction"]["id"]
        fixtures.file_claim(api, deduction_id, AMOUNT_CENTS)

        first = fixtures.substantiate(api, deduction_id, "POD-1001-REV")
        assert first["dispute_state"] == DisputeState.SUBSTANTIATED
        assert first["substantiation_doc_count"] == 1

        second = fixtures.substantiate(api, deduction_id, "SIGNED-BOL-3003")
        assert second["dispute_state"] == DisputeState.SUBSTANTIATED
        assert second["substantiation_doc_count"] == 2
        assert second["settlement_state"] == DeductionSettlementState.OPEN

    def test_approval_is_the_only_step_that_moves_the_money_dimension(self, api, denied_claim):
        """A shortage recovers half the deduction and concedes the rest.

        PRD: "A `SHORTAGE` is capped by a contractual allowance of 5,000 basis points: the
        recoverable amount is the smaller of `claim_amount_cents` and half of `amount_cents`
        floored to whole cents."

        Design: Difficulty/non_linear_state_machine/deduction_settlement_and_dispute_dimensions_advance_independently
        """
        deduction_id = denied_claim["deduction"]["id"]
        refile_and_resubstantiate(api, deduction_id)
        settled = fixtures.approve_recovery(api, deduction_id)

        assert settled["dispute_state"] == DisputeState.APPROVED
        assert settled["settlement_state"] == DeductionSettlementState.RECOVERED
        assert settled["recovered_cents"] == RECOVERABLE_CENTS
        assert settled["recovered_cents"] == expected_shortage_recovery(
            AMOUNT_CENTS, AMOUNT_CENTS
        )
        assert settled["conceded_cents"] == AMOUNT_CENTS - RECOVERABLE_CENTS
        assert settled["open_cents"] == 0
        assert_deduction_money_conserved(settled)

    def test_the_money_identity_holds_at_every_step_of_the_round_trip(self, api, denied_claim):
        """Recovered plus conceded plus open equals the deduction amount throughout.

        PRD: "On a deduction, `amount_cents` always equals `recovered_cents` plus
        `conceded_cents` plus `open_cents`."

        Design: Difficulty/non_linear_state_machine/deduction_settlement_and_dispute_dimensions_advance_independently
        """
        deduction_id = denied_claim["deduction"]["id"]

        for stage in (
            fixtures.get_deduction(api, deduction_id),
            fixtures.file_claim(api, deduction_id, AMOUNT_CENTS),
            fixtures.substantiate(api, deduction_id, "POD-1001-REV"),
            fixtures.substantiate(api, deduction_id, "SIGNED-BOL-3003"),
            fixtures.approve_recovery(api, deduction_id),
        ):
            assert stage["amount_cents"] == AMOUNT_CENTS
            assert_deduction_money_conserved(stage)

    def test_the_filer_and_the_approver_are_recorded_separately(self, api, denied_claim):
        """Segregation of duties is visible on the settled record.

        PRD: "It is exclusive to `BrokerAuditManager`, and the acting `X-User-ID` must differ
        from the `filed_by_user_id` recorded at filing time — the broker employee who files a
        claim can never be the one who approves it, and a self-approval attempt is
        `ERR_SEGREGATION_OF_DUTIES` even though the role is correct."

        Design: Difficulty/non_linear_state_machine/deduction_settlement_and_dispute_dimensions_advance_independently
        """
        deduction_id = denied_claim["deduction"]["id"]
        refile_and_resubstantiate(api, deduction_id)
        settled = fixtures.approve_recovery(api, deduction_id)

        assert settled["filed_by_user_id"] == FILER_USER_ID
        assert settled["approved_by_user_id"] == APPROVER_USER_ID
        assert settled["filed_by_user_id"] != settled["approved_by_user_id"]
