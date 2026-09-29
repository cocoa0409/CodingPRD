"""Approval layers three checks: the dispute state first, then the approver, then the evidence."""

import pytest

from test_helpers import (
    ApiErrorId,
    DeductionReasonCode,
    DeductionSettlementState,
    DisputeState,
    fixtures,
    get_success_data,
    make_account_manager_headers,
    make_audit_manager_headers,
    validate_error,
)
from test_helpers import factories as F
from test_helpers.assertions import (
    assert_deduction_money_conserved,
    expected_shortage_recovery,
)

AMOUNT_CENTS = 80000
RECOVERABLE_CENTS = 40000
DUAL_HAT_USER_ID = "u_dual"
INDEPENDENT_APPROVER_ID = "u_audit_1"


@pytest.fixture
def undisputed_deduction(api):
    """An 80,000 shortage still NOT_DISPUTED with no evidence attached."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    principal = fixtures.create_principal(api, slotting_budget_cents=20000000)
    deduction = fixtures.create_deduction(
        api,
        retailer["id"],
        principal["id"],
        reason_code=DeductionReasonCode.SHORTAGE,
        amount_cents=AMOUNT_CENTS,
        deduction_date="2026-08-01",
    )
    return {"retailer": retailer, "principal": principal, "deduction": deduction}


def file_as_dual_hat(api, scope):
    """The same human files the claim who will later try to approve it."""
    return get_success_data(
        api.dispute_deduction(
            scope["deduction"]["id"],
            F.dispute_payload(AMOUNT_CENTS),
            make_account_manager_headers(DUAL_HAT_USER_ID),
        ),
        200,
    )


def attach_document(api, scope, document_ref):
    return get_success_data(
        api.substantiate_deduction(
            scope["deduction"]["id"],
            F.substantiate_payload(document_ref),
            make_account_manager_headers(DUAL_HAT_USER_ID),
        ),
        200,
    )


def attempt_approval(api, scope, user_id):
    return api.approve_recovery(
        scope["deduction"]["id"], make_audit_manager_headers(user_id)
    )


class TestApproveRecoveryCheckOrder:
    def test_an_undisputed_deduction_cannot_be_approved_at_all(
        self, api, undisputed_deduction
    ):
        """The approver is also the filer-to-be and there is no evidence, yet the state answers.

        PRD: "It moves `dispute_state` from `SUBSTANTIATED` to `APPROVED`, records
        `approved_by_user_id`, and settles the money."

        PRD: "The target must be in a state from which the requested transition exists, and companion
        resources must be in the states the transition names — covering `status` on principals,
        agreements and reviews, `catalog_state` on items, `status` on presentations, `state` on deals
        and promotion events, both `authorization_state` and `settlement_state` on authorizations, and
        both `settlement_state` and `dispute_state` on deductions."

        Design: Corner/validations/approve_recovery_runs_state_then_duties_then_substantiation_checks
        """
        scope = undisputed_deduction
        assert scope["deduction"]["dispute_state"] == DisputeState.NOT_DISPUTED

        response = attempt_approval(api, scope, DUAL_HAT_USER_ID)

        validate_error(response, ApiErrorId.INVALID_STATE, 409)

    def test_a_merely_filed_claim_still_masks_the_identity_clash(
        self, api, undisputed_deduction
    ):
        """FILED is not SUBSTANTIATED, so the priority-7 rung still answers before the approver check.

        PRD: "Substantiation then attaches evidence one document at a time, each call carrying a
        `document_ref`: the first document moves `dispute_state` from `FILED` to `SUBSTANTIATED`, and
        further calls while already `SUBSTANTIATED` are a self-loop that only increments
        `substantiation_doc_count` without changing state."

        Design: Corner/validations/approve_recovery_runs_state_then_duties_then_substantiation_checks
        """
        scope = undisputed_deduction
        filed = file_as_dual_hat(api, scope)
        assert filed["dispute_state"] == DisputeState.FILED
        assert filed["filed_by_user_id"] == DUAL_HAT_USER_ID

        response = attempt_approval(api, scope, DUAL_HAT_USER_ID)

        validate_error(response, ApiErrorId.INVALID_STATE, 409)

    def test_the_segregation_check_is_reported_before_the_evidence_shortfall(
        self, api, undisputed_deduction
    ):
        """One document is not enough either, but the self-approval is the rung reported.

        PRD: "recovery approval and denial are guarded by `ERR_SEGREGATION_OF_DUTIES` (403), and
        approval additionally by `ERR_SUBSTANTIATION_INSUFFICIENT` (409)."

        PRD: "It is exclusive to `BrokerAuditManager`, and the acting `X-User-ID` must differ from the
        `filed_by_user_id` recorded at filing time — the broker employee who files a claim can never be
        the one who approves it, and a self-approval attempt is `ERR_SEGREGATION_OF_DUTIES` even though
        the role is correct."

        Design: Corner/validations/approve_recovery_runs_state_then_duties_then_substantiation_checks
        """
        scope = undisputed_deduction
        file_as_dual_hat(api, scope)
        substantiated = attach_document(api, scope, "POD-9001")
        assert substantiated["dispute_state"] == DisputeState.SUBSTANTIATED
        assert substantiated["substantiation_doc_count"] == 1

        response = attempt_approval(api, scope, DUAL_HAT_USER_ID)

        validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES, 403)

    def test_an_independent_approver_then_meets_the_document_minimum(
        self, api, undisputed_deduction
    ):
        """With the identity clash gone, a single document is the last remaining defect.

        PRD: "Approval further requires at least two substantiation documents, otherwise
        `ERR_SUBSTANTIATION_INSUFFICIENT`, and requires `settlement_state` to still be `OPEN`,
        otherwise `ERR_DEDUCTION_ALREADY_SETTLED`."

        Design: Corner/validations/approve_recovery_runs_state_then_duties_then_substantiation_checks
        """
        scope = undisputed_deduction
        file_as_dual_hat(api, scope)
        attach_document(api, scope, "POD-9001")
        validate_error(
            attempt_approval(api, scope, DUAL_HAT_USER_ID),
            ApiErrorId.SEGREGATION_OF_DUTIES,
            403,
        )

        response = attempt_approval(api, scope, INDEPENDENT_APPROVER_ID)

        validate_error(response, ApiErrorId.SUBSTANTIATION_INSUFFICIENT, 409)
        assert fixtures.get_deduction(api, scope["deduction"]["id"])["dispute_state"] == (
            DisputeState.SUBSTANTIATED
        )

    def test_the_second_document_lets_the_independent_approver_settle_the_money(
        self, api, undisputed_deduction
    ):
        """Half of 80,000 is recoverable under the shortage allowance; the rest is conceded.

        PRD: "A `SHORTAGE` is capped by a contractual allowance of 5,000 basis points: the recoverable
        amount is the smaller of `claim_amount_cents` and half of `amount_cents` floored to whole
        cents."

        PRD: "`settlement_state` moves `OPEN` → `RECOVERED` when the recoverable amount is above
        zero, and `OPEN` → `CONCEDED` when it is zero — so an approved compliance fine still records
        `dispute_state` as `APPROVED` while its money lands in `CONCEDED`."

        Design: Corner/validations/approve_recovery_runs_state_then_duties_then_substantiation_checks
        """
        scope = undisputed_deduction
        file_as_dual_hat(api, scope)
        attach_document(api, scope, "POD-9001")
        second = attach_document(api, scope, "INV-9001")
        assert second["substantiation_doc_count"] == 2

        settled = get_success_data(
            attempt_approval(api, scope, INDEPENDENT_APPROVER_ID), 200
        )

        assert expected_shortage_recovery(AMOUNT_CENTS, AMOUNT_CENTS) == RECOVERABLE_CENTS
        assert settled["recovered_cents"] == RECOVERABLE_CENTS
        assert settled["conceded_cents"] == AMOUNT_CENTS - RECOVERABLE_CENTS
        assert settled["open_cents"] == 0
        assert settled["settlement_state"] == DeductionSettlementState.RECOVERED
        assert settled["dispute_state"] == DisputeState.APPROVED
        assert settled["approved_by_user_id"] == INDEPENDENT_APPROVER_ID
        assert settled["filed_by_user_id"] == DUAL_HAT_USER_ID
        assert_deduction_money_conserved(settled)
