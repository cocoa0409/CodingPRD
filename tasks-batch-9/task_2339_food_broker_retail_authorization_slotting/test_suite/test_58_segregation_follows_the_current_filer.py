"""One human wearing both hats is refused — until a different account manager refiles the claim."""

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

AMOUNT_CENTS = 100000
RECOVERABLE_CENTS = 50000
DUAL_HATTED_ID = "u_dual"
SECOND_MANAGER_ID = "u_am_2"
INDEPENDENT_AUDITOR_ID = "u_audit_1"

DUAL_AS_MANAGER = make_account_manager_headers(DUAL_HATTED_ID)
DUAL_AS_AUDITOR = make_audit_manager_headers(DUAL_HATTED_ID)
SECOND_MANAGER = make_account_manager_headers(SECOND_MANAGER_ID)
INDEPENDENT_AUDITOR = make_audit_manager_headers(INDEPENDENT_AUDITOR_ID)


@pytest.fixture
def claim_filed_and_substantiated_by_a_dual_hatted_identity(api):
    """`u_dual` filed the claim and attached both documents, so only the identity clash is left."""
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
    filed = get_success_data(
        api.dispute_deduction(
            deduction["id"], F.dispute_payload(AMOUNT_CENTS), DUAL_AS_MANAGER
        ),
        200,
    )
    for document_ref in ("POD-A", "INV-A"):
        substantiated = get_success_data(
            api.substantiate_deduction(
                deduction["id"], F.substantiate_payload(document_ref), DUAL_AS_MANAGER
            ),
            200,
        )
    return {
        "retailer": retailer,
        "principal": principal,
        "deduction": deduction,
        "filed": filed,
        "substantiated": substantiated,
    }


def deny_as(api, scope, headers, denial_reason):
    return api.deny_recovery(
        scope["deduction"]["id"], F.deny_payload(denial_reason), headers
    )


def refile_as_the_second_manager(api, scope):
    return get_success_data(
        api.dispute_deduction(
            scope["deduction"]["id"], F.dispute_payload(AMOUNT_CENTS), SECOND_MANAGER
        ),
        200,
    )


def substantiate_as_the_second_manager(api, scope):
    result = None
    for document_ref in ("POD-B", "INV-B"):
        result = get_success_data(
            api.substantiate_deduction(
                scope["deduction"]["id"], F.substantiate_payload(document_ref), SECOND_MANAGER
            ),
            200,
        )
    return result


class TestSegregationFollowsTheCurrentFiler:
    def test_the_filer_identity_is_recorded_and_repeat_documents_only_count(
        self, api, claim_filed_and_substantiated_by_a_dual_hatted_identity
    ):
        """Two documents were attached; the second was a self-loop on an already substantiated claim.

        PRD: "Filing persists the claim, records the acting `X-User-ID` as `filed_by_user_id`, and resets
        `substantiation_doc_count` to 0."

        PRD: "the first document moves `dispute_state` from `FILED` to `SUBSTANTIATED`, and further calls
        while already `SUBSTANTIATED` are a self-loop that only increments `substantiation_doc_count`
        without changing state"

        Design: Corner/rbac/segregation_of_duties_follows_the_current_filer_identity
        """
        scope = claim_filed_and_substantiated_by_a_dual_hatted_identity

        assert scope["filed"]["filed_by_user_id"] == DUAL_HATTED_ID
        assert scope["substantiated"]["dispute_state"] == DisputeState.SUBSTANTIATED
        assert scope["substantiated"]["substantiation_doc_count"] == 2

    def test_the_audit_role_can_neither_file_nor_substantiate_a_claim_of_its_own(
        self, api, claim_filed_and_substantiated_by_a_dual_hatted_identity
    ):
        """The structural half of the control: audit has no way to manufacture the evidence it rules on.

        PRD: "| POST | `/deductions/{deductionId}/substantiate` | Attach one substantiation document to a
        filed claim | BrokerAccountManager |"

        PRD: "`BrokerAuditManager` — the broker's deduction-audit control. The sole approver or denier of
        a post-audit recovery."

        Design: Corner/rbac/segregation_of_duties_follows_the_current_filer_identity
        """
        scope = claim_filed_and_substantiated_by_a_dual_hatted_identity
        deduction_id = scope["deduction"]["id"]

        validate_error(
            api.dispute_deduction(
                deduction_id, F.dispute_payload(AMOUNT_CENTS), INDEPENDENT_AUDITOR
            ),
            ApiErrorId.ROLE_FORBIDDEN,
            403,
        )
        validate_error(
            api.substantiate_deduction(
                deduction_id, F.substantiate_payload("FAKE-1"), INDEPENDENT_AUDITOR
            ),
            ApiErrorId.ROLE_FORBIDDEN,
            403,
        )

    def test_the_filer_may_not_approve_its_own_claim(
        self, api, claim_filed_and_substantiated_by_a_dual_hatted_identity
    ):
        """The role is right and the evidence is sufficient, so only the identity clash is wrong.

        PRD: "It is exclusive to `BrokerAuditManager`, and the acting `X-User-ID` must differ from the
        `filed_by_user_id` recorded at filing time — the broker employee who files a claim can never be
        the one who approves it, and a self-approval attempt is `ERR_SEGREGATION_OF_DUTIES` even though
        the role is correct."

        PRD: "**Safety and compliance.** Presentation submission is guarded by `ERR_PRINCIPAL_CONFLICT`
        and `ERR_CATEGORY_EXCLUSIVITY` (both 409); recovery approval and denial are guarded by
        `ERR_SEGREGATION_OF_DUTIES` (403), and approval additionally by
        `ERR_SUBSTANTIATION_INSUFFICIENT` (409)."

        Design: Corner/rbac/segregation_of_duties_follows_the_current_filer_identity
        """
        scope = claim_filed_and_substantiated_by_a_dual_hatted_identity

        response = api.approve_recovery(scope["deduction"]["id"], DUAL_AS_AUDITOR)

        validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES, 403)
        assert fixtures.get_deduction(api, scope["deduction"]["id"])["dispute_state"] == (
            DisputeState.SUBSTANTIATED
        )

    def test_the_filer_may_not_quietly_deny_its_own_claim_either(
        self, api, claim_filed_and_substantiated_by_a_dual_hatted_identity
    ):
        """The control covers both audit verbs, not just the one that moves money.

        PRD: "It does compare those two recorded identifiers to each other: the segregation-of-duties
        control described in §3.9 requires that the `BrokerAuditManager` approving or denying a recovery
        is not the same `X-User-ID` that filed the claim, and a violation returns
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) even though the role itself is correct."

        PRD: "Also exclusive to `BrokerAuditManager` and also subject to the same segregation check
        against `filed_by_user_id`"

        Design: Corner/rbac/segregation_of_duties_follows_the_current_filer_identity
        """
        scope = claim_filed_and_substantiated_by_a_dual_hatted_identity

        response = deny_as(api, scope, DUAL_AS_AUDITOR, "self-denial attempt")

        validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES, 403)
        assert fixtures.get_deduction(api, scope["deduction"]["id"])["denial_reason"] is None

    def test_an_independent_auditor_may_deny_and_the_denial_records_no_approver(
        self, api, claim_filed_and_substantiated_by_a_dual_hatted_identity
    ):
        """Denial records a reason, not an approver, and it leaves the money where it was.

        PRD: "Denial is the mirror image and is deliberately money-neutral."

        PRD: "A new deduction begins with `settlement_state` at `OPEN`, `dispute_state` at
        `NOT_DISPUTED`, `open_cents` equal to `amount_cents`, `claim_amount_cents`, `recovered_cents`,
        `conceded_cents`, `substantiation_doc_count` and `refile_count` all at 0, and
        `filed_by_user_id`, `approved_by_user_id` and `denial_reason` all null."

        Design: Corner/rbac/segregation_of_duties_follows_the_current_filer_identity
        """
        scope = claim_filed_and_substantiated_by_a_dual_hatted_identity

        denied = get_success_data(
            deny_as(api, scope, INDEPENDENT_AUDITOR, "Documents do not match the invoice"), 200
        )

        assert denied["dispute_state"] == DisputeState.DENIED
        assert denied["approved_by_user_id"] is None
        assert denied["open_cents"] == AMOUNT_CENTS

    def test_a_refile_by_a_different_manager_overwrites_the_recorded_filer(
        self, api, claim_filed_and_substantiated_by_a_dual_hatted_identity
    ):
        """The check has a moving target: the current filer, not any historical participant.

        PRD: "A refile increases `refile_count` by one, resets `substantiation_doc_count` to 0 so
        evidence must be assembled afresh, clears `denial_reason` to null, and records the new
        `filed_by_user_id`."

        Design: Corner/rbac/segregation_of_duties_follows_the_current_filer_identity
        """
        scope = claim_filed_and_substantiated_by_a_dual_hatted_identity
        get_success_data(
            deny_as(api, scope, INDEPENDENT_AUDITOR, "Documents do not match the invoice"), 200
        )

        refiled = refile_as_the_second_manager(api, scope)

        assert refiled["filed_by_user_id"] == SECOND_MANAGER_ID
        assert refiled["refile_count"] == 1
        assert refiled["substantiation_doc_count"] == 0
        assert refiled["denial_reason"] is None

    def test_the_once_refused_identity_becomes_a_legitimate_approver(
        self, api, claim_filed_and_substantiated_by_a_dual_hatted_identity
    ):
        """`u_dual` is no longer the filer, so the very same call now settles the deduction.

        PRD: "It moves `dispute_state` from `SUBSTANTIATED` to `APPROVED`, records
        `approved_by_user_id`, and settles the money."

        PRD: "A `SHORTAGE` is capped by a contractual allowance of 5,000 basis points: the recoverable
        amount is the smaller of `claim_amount_cents` and half of `amount_cents` floored to whole cents."

        Design: Corner/rbac/segregation_of_duties_follows_the_current_filer_identity
        """
        scope = claim_filed_and_substantiated_by_a_dual_hatted_identity
        get_success_data(
            deny_as(api, scope, INDEPENDENT_AUDITOR, "Documents do not match the invoice"), 200
        )
        refile_as_the_second_manager(api, scope)
        substantiate_as_the_second_manager(api, scope)
        validate_error(
            api.approve_recovery(scope["deduction"]["id"], SECOND_MANAGER),
            ApiErrorId.ROLE_FORBIDDEN,
            403,
        )

        approved = get_success_data(
            api.approve_recovery(scope["deduction"]["id"], DUAL_AS_AUDITOR), 200
        )

        assert approved["dispute_state"] == DisputeState.APPROVED
        assert approved["approved_by_user_id"] == DUAL_HATTED_ID
        assert approved["filed_by_user_id"] == SECOND_MANAGER_ID

    def test_the_settlement_splits_the_shortage_in_half(
        self, api, claim_filed_and_substantiated_by_a_dual_hatted_identity
    ):
        """Half of 100,000 is recoverable and the other half is conceded, leaving nothing open.

        PRD: "Settlement then follows uniformly for every reason code: `recovered_cents` is set to the
        recoverable amount, `conceded_cents` to `amount_cents` less that amount, and `open_cents`
        consequently to zero."

        PRD: "`settlement_state` moves `OPEN` → `RECOVERED` when the recoverable amount is above zero,
        and `OPEN` → `CONCEDED` when it is zero — so an approved compliance fine still records
        `dispute_state` as `APPROVED` while its money lands in `CONCEDED`."

        Design: Corner/rbac/segregation_of_duties_follows_the_current_filer_identity
        """
        scope = claim_filed_and_substantiated_by_a_dual_hatted_identity
        get_success_data(
            deny_as(api, scope, INDEPENDENT_AUDITOR, "Documents do not match the invoice"), 200
        )
        refile_as_the_second_manager(api, scope)
        substantiate_as_the_second_manager(api, scope)

        approved = get_success_data(
            api.approve_recovery(scope["deduction"]["id"], DUAL_AS_AUDITOR), 200
        )

        assert approved["settlement_state"] == DeductionSettlementState.RECOVERED
        assert approved["recovered_cents"] == RECOVERABLE_CENTS
        assert approved["conceded_cents"] == AMOUNT_CENTS - RECOVERABLE_CENTS
        assert approved["open_cents"] == 0
