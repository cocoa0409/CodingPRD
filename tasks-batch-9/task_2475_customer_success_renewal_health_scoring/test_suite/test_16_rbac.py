"""Role and identity gates: role lists, segregation of duties, handoff ownership.

The first two classes exercise the role-list gate of PRD §2.1. The last two
exercise the narrower gates PRD §2.1 enforces by comparing `X-User-ID` rather
than the role name, so each of them acts twice with the same role and two
different user identifiers.
"""

from test_helpers import (
    ADVOCACY_HEADERS,
    ApiClient,
    ApiErrorId,
    COMMITMENT_ACCEPTED,
    COMMITMENT_ACTION_DELIVER,
    COMMITMENT_DELIVERED,
    EXECUTIVE_HEADERS,
    EXECUTIVE_USER_ID,
    ENROLLMENT_NOMINATED,
    FINANCE_HEADERS,
    OPPORTUNITY_ACCEPTED,
    OPPORTUNITY_ACTION_ACCEPT,
    OPPORTUNITY_ACTION_HANDOFF,
    OPPORTUNITY_HANDED_OFF,
    OPS_ADMIN_HEADERS,
    OTHER_SALES_HEADERS,
    PROGRAM_REFERENCE,
    SALES_AE_USER_ID,
    SALES_HEADERS,
    SECOND_EXECUTIVE_HEADERS,
    SECOND_EXECUTIVE_USER_ID,
    assert_created,
    assert_credit_ledger,
    assert_field,
    assert_fields,
    assert_null,
    assert_ok,
    assert_page,
    assert_score,
    factories,
    identify_opportunity,
    read_account,
    read_commitment,
    read_opportunity,
    validate_error,
)


class TestAccountCreationIsOpsOnly:
    """Registering an account belongs to CS operations alone."""

    def test_finance_analyst_cannot_create_an_account(self, api: ApiClient) -> None:
        """A FinanceAnalyst is off the role list for account registration, so 403.

        PRD §2.1: "If the headers are well-formed but the named role does not appear in the authorized-role list that §4 publishes for the requested endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "The system recognises exactly six roles, spelled: `CsmUser`, `CsOpsAdmin`, `CsExecutive`, `FinanceAnalyst`, `SalesAccountExecutive`, and `AdvocacyManager`."

        Design: Corner/rbac/finance_analyst_cannot_create_an_account_returns_unauthorized
        """
        response = api.create_account(
            factories.account(name="Finance Attempted Co"), FINANCE_HEADERS
        )

        validate_error(response, ApiErrorId.UNAUTHORIZED)
        assert_page(api.list_accounts(OPS_ADMIN_HEADERS), expected_total=0)


class TestAdvocacyEnrollmentIsAdvocacyManagerOnly:
    """Nominating an account into a programme belongs to the advocacy manager."""

    def test_csm_user_is_refused(self, api: ApiClient, roster_and_account) -> None:
        """A CsmUser is off the role list for nomination, so 403 and no row is written.

        PRD §2.1: "If the headers are well-formed but the named role does not appear in the authorized-role list that §4 publishes for the requested endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §3.8: "Advocacy is the reward the strongest accounts earn, and an advocacy manager owns the whole progression."

        Design: Corner/rbac/csm_user_cannot_create_an_advocacy_enrollment_but_advocacy_manager_can
        """
        response = api.create_advocacy_enrollment(
            roster_and_account["account_id"],
            factories.advocacy_enrollment(PROGRAM_REFERENCE),
            roster_and_account["csm_headers"],
        )

        validate_error(response, ApiErrorId.UNAUTHORIZED)
        assert_page(
            api.list_advocacy_enrollments(
                roster_and_account["account_id"], ADVOCACY_HEADERS
            ),
            expected_total=0,
        )

    def test_advocacy_manager_succeeds(
        self, api: ApiClient, roster_and_account
    ) -> None:
        """The same body from an AdvocacyManager creates a NOMINATED enrollment.

        PRD §2.1: "If the headers are well-formed but the named role does not appear in the authorized-role list that §4 publishes for the requested endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §3.8: "It begins in state `NOMINATED` with `reference_calls_used` 0, `last_reference_call_at` null, and its own `reference_calls_cap` **snapshotted** from the account's `reference_calls_cap` at creation: 6 for an `ENTERPRISE` account, 4 for `MIDMARKET`, 2 for `SMB`."

        Design: Corner/rbac/csm_user_cannot_create_an_advocacy_enrollment_but_advocacy_manager_can
        """
        enrollment = assert_created(
            api.create_advocacy_enrollment(
                roster_and_account["account_id"],
                factories.advocacy_enrollment(PROGRAM_REFERENCE),
                ADVOCACY_HEADERS,
            )
        )

        assert_fields(
            enrollment,
            {
                "state": ENROLLMENT_NOMINATED,
                "program_type": PROGRAM_REFERENCE,
                "reference_calls_used": 0,
                "reference_calls_cap": 6,
            },
        )
        assert_null(enrollment, "last_reference_call_at")


class TestCommitmentSegregationOfDuties:
    """Delivery is refused to the identifier that accepted, whatever its role."""

    def test_accepting_user_cannot_deliver(self, api: ApiClient, committed_case) -> None:
        """The CS executive who accepted the commitment is refused delivery with 403.

        PRD §2.1: "And the actor who marked a remediation commitment accepted may not also mark it delivered: a delivery attempt whose `X-User-ID` equals the commitment's `accepted_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §3.5: "Delivering a commitment carries it `ACCEPTED → DELIVERED`, requires the case to be in state `COMMITTED`, and — this is the segregation-of-duties rule — requires that the acting `X-User-ID` differ from the commitment's `accepted_by_user_id`; the same human may not both accept and deliver, and an attempt is refused with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.5: "The rule is keyed on the user identifier, not on the role, so two different CS executives satisfy it while one executive acting twice does not."

        Design: Corner/rbac/delivering_a_commitment_the_same_user_accepted_returns_segregation_of_duties
        """
        commitment = read_commitment(
            api, committed_case["case_id"], committed_case["commitment_id"]
        )
        assert_field(commitment, "accepted_by_user_id", EXECUTIVE_USER_ID)

        response = api.transition_remediation_commitment(
            committed_case["commitment_id"],
            factories.commitment_transition(COMMITMENT_ACTION_DELIVER),
            EXECUTIVE_HEADERS,
        )

        validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES)
        unchanged = read_commitment(
            api, committed_case["case_id"], committed_case["commitment_id"]
        )
        assert_field(unchanged, "state", COMMITMENT_ACCEPTED)
        assert_null(unchanged, "delivered_by_user_id")
        assert_credit_ledger(
            read_account(api, committed_case["account_id"]), 600_000, 0
        )

    def test_a_second_executive_can_deliver(
        self, api: ApiClient, committed_case
    ) -> None:
        """A different CS executive delivers the same commitment and the credit stays owed.

        PRD §3.5: "The rule is keyed on the user identifier, not on the role, so two different CS executives satisfy it while one executive acting twice does not."
        PRD §3.5: "Delivery stamps `delivered_by_user_id` and deliberately leaves `remediation_credit_outstanding_cents` unchanged: a delivered credit is still owed to the customer until the case settles."

        Design: Corner/rbac/delivering_a_commitment_the_same_user_accepted_returns_segregation_of_duties
        """
        delivered = assert_ok(
            api.transition_remediation_commitment(
                committed_case["commitment_id"],
                factories.commitment_transition(COMMITMENT_ACTION_DELIVER),
                SECOND_EXECUTIVE_HEADERS,
            )
        )

        assert_fields(
            delivered,
            {
                "state": COMMITMENT_DELIVERED,
                "accepted_by_user_id": EXECUTIVE_USER_ID,
                "delivered_by_user_id": SECOND_EXECUTIVE_USER_ID,
            },
        )
        assert_credit_ledger(
            read_account(api, committed_case["account_id"]), 600_000, 0
        )


class TestHandoffOwnership:
    """Only the account executive named at handoff may dispose of the opportunity."""

    def _handed_off(self, api: ApiClient, state) -> dict:
        """Identify an opportunity on the OPEN account and hand it to the named AE."""
        opportunity = identify_opportunity(api, state["account_id"], state["csm_id"])
        assert_score(
            opportunity["qualification_score"], 65.70, "qualification_score"
        )
        handed = assert_ok(
            api.transition_expansion_opportunity(
                opportunity["id"],
                factories.opportunity_transition(
                    OPPORTUNITY_ACTION_HANDOFF, handoff_ae_user_id=SALES_AE_USER_ID
                ),
                state["csm_headers"],
            )
        )
        assert_fields(
            handed,
            {
                "state": OPPORTUNITY_HANDED_OFF,
                "handoff_ae_user_id": SALES_AE_USER_ID,
            },
        )
        return handed

    def test_other_sales_ae_cannot_accept(self, api: ApiClient, open_account) -> None:
        """A second SalesAccountExecutive is refused with 403 and the row stays HANDED_OFF.

        PRD §2.1: "A `SalesAccountExecutive` may accept or reject an expansion opportunity only when the acting `X-User-ID` equals the `handoff_ae_user_id` recorded on that opportunity; any other executive is refused with `ERR_NOT_HANDOFF_OWNER` (HTTP 403)."
        PRD §3.7: "Both actions require that the acting `X-User-ID` equal the opportunity's `handoff_ae_user_id`; any other user — including a different sales account executive — is refused with `ERR_NOT_HANDOFF_OWNER`."
        PRD §3.7: "The health input is the **trailing** figure and never the point-in-time one: an account with a `trended_health_score` of 67.20, an `adoption_index` of 67.00 and `arr_cents` of 30,000,000 has a revenue term of 60.00 and a `qualification_score` of 33.60 plus 20.10 plus 12.00, or 65.70 — which clears the handoff floor, whereas substituting the point-in-time figure of 73.85 would give 69.03 and a materially different pipeline."

        Design: Corner/rbac/a_sales_ae_who_is_not_the_handoff_owner_cannot_accept_the_opportunity
        """
        handed = self._handed_off(api, open_account)

        response = api.transition_expansion_opportunity(
            handed["id"],
            factories.opportunity_transition(OPPORTUNITY_ACTION_ACCEPT),
            OTHER_SALES_HEADERS,
        )

        validate_error(response, ApiErrorId.NOT_HANDOFF_OWNER)
        unchanged = read_opportunity(api, handed["id"])
        assert_fields(
            unchanged,
            {
                "state": OPPORTUNITY_HANDED_OFF,
                "handoff_ae_user_id": SALES_AE_USER_ID,
            },
        )

    def test_named_sales_ae_can_accept(self, api: ApiClient, open_account) -> None:
        """The identifier recorded at handoff accepts the same opportunity.

        PRD §3.7: "Both actions require that the acting `X-User-ID` equal the opportunity's `handoff_ae_user_id`; any other user — including a different sales account executive — is refused with `ERR_NOT_HANDOFF_OWNER`."
        PRD §3.7: "Accepting carries `HANDED_OFF → ACCEPTED`; rejecting carries `HANDED_OFF → REJECTED` and requires a `rejection_reason`, which is stored on the row."

        Design: Corner/rbac/a_sales_ae_who_is_not_the_handoff_owner_cannot_accept_the_opportunity
        """
        handed = self._handed_off(api, open_account)

        accepted = assert_ok(
            api.transition_expansion_opportunity(
                handed["id"],
                factories.opportunity_transition(OPPORTUNITY_ACTION_ACCEPT),
                SALES_HEADERS,
            )
        )

        assert_fields(
            accepted,
            {
                "state": OPPORTUNITY_ACCEPTED,
                "handoff_ae_user_id": SALES_AE_USER_ID,
            },
        )
