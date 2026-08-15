"""Damage claims: review/dispute cycle, approved-amount guard, and
segregation of duties at crediting time."""
from test_helpers import (
    TEST_USERS,
    api_client,
    build_user_headers,
    get_success_data,
    make_contractor_headers,
    setup_approved_claim,
    setup_filed_claim,
    validate_error,
    validate_success,
    ApiErrorId,
)

MANAGER = TEST_USERS["branch_manager_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]
CREDIT = TEST_USERS["credit_analyst_headers"]


class TestDisputeReviewCycle:
    def test_dispute_and_re_review_increments_review_round(self, api):
        """PRD §3.8: "An owning `Contractor` who disagrees with an approved
        figure may dispute it — the claim must be `APPROVED` (otherwise
        `ERR_CLAIM_NOT_APPROVED`) and acting on someone else's job is
        `ERR_FORBIDDEN` — sending the claim to `DISPUTED`, from which a fresh
        review round begins."
        PRD §3.8: "re-entering review from `DISPUTED` increments
        `review_round` by one."

        Design: Difficulty/non_linear_state_machine/damage_claim_dispute_review_cycle
        """
        ctx = setup_approved_claim(approved_amount_cents=5000,
                                   branch_code="BR-CL1", sku="SH-CL1",
                                   price=3000, claimed_bundles=5)
        disputed = validate_success(api_client.dispute_claim(
            ctx["claim"]["id"],
            make_contractor_headers(ctx["account"]["id"])))
        assert disputed["status"] == "DISPUTED"
        re_reviewed = validate_success(
            api_client.start_claim_review(ctx["claim"]["id"], ADJUSTER))
        assert re_reviewed["status"] == "UNDER_REVIEW"
        assert re_reviewed["review_round"] == 2

    def test_first_review_from_filed_keeps_round_one(self, api):
        """PRD §3.8: "A `ClaimsAdjuster` opens the file by starting review,
        permitted from `FILED` or from `DISPUTED` (from anywhere else,
        `ERR_CLAIM_NOT_FILED`); re-entering review from `DISPUTED` increments
        `review_round` by one."

        Filing stamps `review_round` one; only the DISPUTED re-entry bumps it.

        Design: Difficulty/non_linear_state_machine/damage_claim_dispute_review_cycle
        """
        ctx = setup_filed_claim(claimed_bundles=5, branch_code="BR-CL2",
                                sku="SH-CL2", price=3000)
        assert ctx["claim"]["review_round"] == 1
        under_review = validate_success(
            api_client.start_claim_review(ctx["claim"]["id"], ADJUSTER))
        assert under_review["status"] == "UNDER_REVIEW"
        assert under_review["review_round"] == 1


class TestSegregationOfDuties:
    def test_credit_by_approving_user_rejected(self, api):
        """PRD §3.8: "Crediting an approved claim is a `CreditAnalyst` action
        requiring the claim in `APPROVED` (otherwise
        `ERR_CLAIM_NOT_APPROVED`), and the crediting user must be a different
        person than the user who approved the claim — the same `X-User-ID` on
        both actions is rejected with `ERR_SOD_VIOLATION` (HTTP 403)."

        The claim is APPROVED (state check passes); only the same-user safety
        check fires.

        Design: Difficulty/priority_pair_validation_conflict/claim_credit_sod_vs_bad_state_sod_wins
        """
        ctx = setup_approved_claim(approved_amount_cents=5000,
                                   approver_id="adj-1", branch_code="BR-V2",
                                   sku="SH-V2", price=3000, claimed_bundles=3)
        resp = api_client.credit_claim(
            ctx["claim"]["id"],
            build_user_headers("adj-1", "CreditAnalyst"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

    def test_credit_by_different_credit_analyst_succeeds(self, api):
        """PRD §3.8: "the crediting user must be a different person than the
        user who approved the claim — the same `X-User-ID` on both actions is
        rejected with `ERR_SOD_VIOLATION` (HTTP 403)."
        PRD §3.8: "The claim itself settles into the terminal `CREDITED`
        state."

        Control arm: a different crediting user passes the SoD gate.

        Design: Difficulty/priority_pair_validation_conflict/claim_credit_sod_vs_bad_state_sod_wins
        """
        ctx = setup_approved_claim(approved_amount_cents=5000,
                                   approver_id="adj-1", branch_code="BR-V3",
                                   sku="SH-V3", price=3000, claimed_bundles=3)
        credited = validate_success(api_client.credit_claim(
            ctx["claim"]["id"],
            build_user_headers("cred-2", "CreditAnalyst")))
        assert credited["status"] == "CREDITED"


class TestApprovedAmountGuard:
    def test_approve_above_claim_amount_rejected(self, api):
        """PRD §3.8: "both transitions requiring `UNDER_REVIEW` (otherwise
        `ERR_CLAIM_NOT_UNDER_REVIEW`) and approval requiring the approved
        amount to be greater than zero and no more than the
        `claim_amount_cents` (otherwise `ERR_INVALID_APPROVED_AMOUNT`); the
        approved figure may differ from the filed amount."

        The claim is 5 bundles * 3000 = 15000; approving 99999 exceeds it.

        Design: Corner/errors/error_claim_approved_amount_over_claim
        """
        ctx = setup_filed_claim(claimed_bundles=5, branch_code="BR-ER4",
                                sku="SH-ER4", price=3000)
        assert ctx["claim"]["claim_amount_cents"] == 15000
        get_success_data(api_client.start_claim_review(ctx["claim"]["id"],
                                                       ADJUSTER))
        resp = api_client.approve_claim(ctx["claim"]["id"], 99999, ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_INVALID_APPROVED_AMOUNT)

    def test_claims_adjuster_cannot_credit_claim(self, api):
        """PRD §2.1: "Each endpoint admits a fixed set of roles (§4); a caller
        whose role is not admitted, or a `Contractor` attempting to act on
        another contractor's resources, is rejected with `ERR_FORBIDDEN` (HTTP
        403)."
        PRD §4: POST /roofing/damage-claims/{id}/credit — "Credit an approved
        claim to the contractor account (SoD enforced) | CreditAnalyst".

        Design: Corner/rbac/claims_adjuster_cannot_credit_claim
        """
        ctx = setup_approved_claim(approved_amount_cents=3000,
                                   approver_id="adj-9", branch_code="BR-RB2",
                                   sku="SH-RB2", price=3000, claimed_bundles=2)
        resp = api_client.credit_claim(
            ctx["claim"]["id"],
            build_user_headers("adj-9", "ClaimsAdjuster"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
