"""Corner queue: account opening gates and lifecycle transitions."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_account,
    begin_edd_review,
    begin_investigation,
    certify,
    complete_edd_review,
    create_account,
    create_certification,
    create_customer,
    create_edd_review,
    create_manual_case,
    create_rep,
    get_account,
    set_clock,
    setup_open_account,
    setup_pending_account,
    submit_and_verify_document,
    submit_document,
    add_owner,
    validate_error,
    validate_success,
)
from test_helpers.test_users import make_rep_headers


class TestAccountInitialStatePendingApproval:
    def test_new_account_pending_approval_standard_posture_initial_variant(self, api):
        """PRD §3.3: "The account enters `PENDING_APPROVAL` with `aml_posture` set to
        `STANDARD`, and the system immediately computes the account's initial risk
        profile."
        PRD §3.3: "These static components are the whole story at creation: the
        `INITIAL` variant of the score adds no activity component at all".

        Design: Corner/state_machines/account_initial_state_pending_approval
        """
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep S1", crd_number="CRD-S01")
        customer = create_customer(
            rep, customer_type="INDIVIDUAL", full_name="S1", tax_id="TIN-S01",
            country_risk_tier="LOW",
        )
        account = create_account(customer["id"], rep, product_set=["CASH"])
        assert account["lifecycle_status"] == "PENDING_APPROVAL"
        assert account["aml_posture"] == "STANDARD"
        assert account["risk_variant_used"] == "INITIAL"


class TestCipIncompleteBlocksApprove:
    def test_individual_without_verified_government_id_blocked_then_unblocked(self, api):
        """PRD §3.3: "First, CIP must be complete: an `INDIVIDUAL` customer needs at
        least one `VERIFIED` document of type `GOVERNMENT_ID`, while a `LEGAL_ENTITY`
        customer needs `VERIFIED` documents of both `FORMATION_DOC` and
        `PROOF_OF_ADDRESS` types — shortfalls are rejected with `ERR_CIP_INCOMPLETE`."
        A verified W9 does not satisfy the GOVERNMENT_ID requirement; verifying one
        unblocks the approval.

        Design: Corner/validations/cip_incomplete_blocks_approve
        """
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep V9", crd_number="CRD-V09")
        customer = create_customer(
            rep, customer_type="INDIVIDUAL", full_name="V9", tax_id="TIN-V09",
            country_risk_tier="LOW",
        )
        submit_and_verify_document(
            customer["id"], rep, doc_type="W9", document_number="W-V09"
        )
        account = create_account(customer["id"], rep, product_set=["CASH"])
        doc2 = submit_document(customer["id"], rep, document_number="G-V09")

        resp = api_client.approve_account(account["id"], TEST_USERS["officer_headers"])
        error = validate_error(resp, ApiErrorId.ERR_CIP_INCOMPLETE)
        assert error["error_id"] == "ERR_CIP_INCOMPLETE"

        resp = api_client.verify_document(doc2["id"], TEST_USERS["analyst_headers"])
        validate_success(resp)
        approved = approve_account(account["id"])
        assert approved["lifecycle_status"] == "OPEN"


class TestProhibitedCountryForcesProhibitedTier:
    def test_prohibited_tier_regardless_of_score_and_never_approved(self, api):
        """PRD §3.3: "a customer whose `country_risk_tier` is `PROHIBITED` is assigned
        risk tier `PROHIBITED` outright, regardless of any score arithmetic."
        PRD §3.3: "a `PROHIBITED` risk tier can never be approved, under any
        circumstance: `ERR_PROHIBITED_TIER`."

        Design: Corner/calculations/prohibited_country_forces_prohibited_tier
        """
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep C1", crd_number="CRD-C01")
        customer = create_customer(
            rep, customer_type="INDIVIDUAL", full_name="C1", tax_id="TIN-C01",
            country_risk_tier="PROHIBITED",
        )
        submit_and_verify_document(customer["id"], rep, document_number="P-C01")
        account = create_account(customer["id"], rep, product_set=["CASH"])
        assert account["risk_score"] == 0, (
            f"no named component contributes points here, got {account['risk_score']}"
        )
        assert account["risk_tier"] == "PROHIBITED", (
            "the PROHIBITED override stands above all scoring"
        )

        resp = api_client.approve_account(account["id"], TEST_USERS["officer_headers"])
        error = validate_error(resp, ApiErrorId.ERR_PROHIBITED_TIER)
        assert error["error_id"] == "ERR_PROHIBITED_TIER"
        assert resp.status_code == 403


class TestLegalEntityApprovalRequiresCertifiedOwnership:
    def test_draft_certification_blocks_then_certified_unblocks(self, api):
        """PRD §3.3: "Second, a `LEGAL_ENTITY` customer must have a certification in
        `CERTIFIED` status, else `ERR_BENEFICIAL_OWNERSHIP_REQUIRED`."

        Design: Corner/validations/legal_entity_approval_requires_certified_ownership
        """
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep V8", crd_number="CRD-V08")
        customer = create_customer(
            rep, customer_type="LEGAL_ENTITY", full_name="V8 Corp",
            tax_id="EIN-V08", country_risk_tier="LOW",
        )
        submit_and_verify_document(
            customer["id"], rep, doc_type="FORMATION_DOC", document_number="F-V08"
        )
        submit_and_verify_document(
            customer["id"], rep, doc_type="PROOF_OF_ADDRESS", document_number="A-V08"
        )
        account = create_account(customer["id"], rep, product_set=["CASH"])
        cert = create_certification(customer["id"], rep)
        add_owner(cert["id"], rep, full_name="Owner100", ownership_pct=100.00,
                  is_control_person=True, tax_id="TIN-O100",
                  date_of_birth="1963-01-01", address="100 St")

        resp = api_client.approve_account(account["id"], TEST_USERS["officer_headers"])
        error = validate_error(resp, ApiErrorId.ERR_BENEFICIAL_OWNERSHIP_REQUIRED)
        assert error["error_id"] == "ERR_BENEFICIAL_OWNERSHIP_REQUIRED"
        assert resp.status_code == 422

        certified = certify(cert["id"])
        assert certified["status"] == "CERTIFIED"
        approved = approve_account(account["id"])
        assert approved["lifecycle_status"] == "OPEN"


class TestAccountReinstateFromOpenRejected:
    def test_reinstate_defined_only_from_restricted(self, api):
        """PRD §3.3: "Reinstatement returns a `RESTRICTED` account to `OPEN`" — and
        PRD §2.9: "6. Target lifecycle and actionability — the target resource must be
        in a state that permits the operation (account lifecycle for posting,
        actionable-state rules for reviews, alerts, cases, matches, deposits, findings,
        engagements, certifications, documents, transactions, filings, and requests),
        and OCC expected-version fields must match; violations surface as the
        appropriate state error from §5". On an OPEN account the lifecycle error is
        `ERR_INVALID_LIFECYCLE_TRANSITION` (409).

        Design: Corner/state_machines/account_reinstate_from_open_rejected
        """
        ctx = setup_open_account()
        resp = api_client.reinstate_account(
            ctx["account"]["id"], TEST_USERS["officer_headers"]
        )
        error = validate_error(resp, ApiErrorId.ERR_INVALID_LIFECYCLE_TRANSITION)
        assert error["error_id"] == "ERR_INVALID_LIFECYCLE_TRANSITION"
        assert resp.status_code == 409
        assert get_account(ctx["account"]["id"])["lifecycle_status"] == "OPEN"


class TestAccountCloseTerminalLockdown:
    def test_closed_account_rejects_further_lifecycle_actions(self, api):
        """PRD §3.3: "`CLOSED` and `DECLINED` are terminal — any further lifecycle
        transition from them is rejected with `ERR_ACCOUNT_CLOSED_TERMINAL`."

        Design: Corner/state_machines/account_close_terminal_lockdown
        """
        ctx = setup_open_account()
        resp = api_client.close_account(ctx["account"]["id"], TEST_USERS["officer_headers"])
        closed = validate_success(resp)
        assert closed["lifecycle_status"] == "CLOSED"

        resp = api_client.restrict_account(
            ctx["account"]["id"], {"reason": "too late"}, TEST_USERS["officer_headers"]
        )
        error = validate_error(resp, ApiErrorId.ERR_ACCOUNT_CLOSED_TERMINAL)
        assert error["error_id"] == "ERR_ACCOUNT_CLOSED_TERMINAL"
        assert get_account(ctx["account"]["id"])["lifecycle_status"] == "CLOSED"


class TestAccountCloseBlockedByOpenCase:
    def test_open_case_blocks_close_until_case_closed(self, api):
        """PRD §3.3: "Closure, from either `OPEN` or `RESTRICTED`, is barred while any
        of four classes of open items exist: a case in `OPEN`, `INVESTIGATING`,
        `SAR_RECOMMENDED`, `REOPENED`, `DECIDED_FILED`, or `DECIDED_NO_FILE`; a match
        in `PENDING_REVIEW` or `CONFIRMED`; a certificate deposit in any state other
        than `ACCEPTED`, `REJECTED`, or `REJECTED_SUSPICIOUS`; or a transaction in
        `FLAGGED` or `ESCALATED`. Each of these blocks surfaces as
        `ERR_ACCOUNT_CLOSE_BLOCKED`."

        Design: Corner/state_machines/account_close_blocked_by_open_case
        """
        ctx = setup_open_account()
        account_id = ctx["account"]["id"]
        case = create_manual_case(account_id)

        resp = api_client.close_account(account_id, TEST_USERS["officer_headers"])
        error = validate_error(resp, ApiErrorId.ERR_ACCOUNT_CLOSE_BLOCKED)
        assert error["error_id"] == "ERR_ACCOUNT_CLOSE_BLOCKED"

        begin_investigation(case["id"])
        resp = api_client.decide_no_file(
            case["id"], {"rationale": "benign"}, TEST_USERS["sar_officer_headers"]
        )
        validate_success(resp)
        resp = api_client.close_case(case["id"], TEST_USERS["sar_officer_headers"])
        validate_success(resp)

        resp = api_client.close_account(account_id, TEST_USERS["officer_headers"])
        closed = validate_success(resp)
        assert closed["lifecycle_status"] == "CLOSED"


class TestEddRejectionCascadesAccountDeclined:
    def test_rejected_edd_review_declines_pending_account(self, api):
        """PRD §3.4: "A completion with decision `REJECTED` cascades to the account:
        if the account is still `PENDING_APPROVAL` it moves to `DECLINED` with the EDD
        rejection recorded in `decline_reason`".

        Design: Corner/state_machines/edd_rejection_cascades_account_declined
        """
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep S6", crd_number="CRD-S06")
        customer = create_customer(
            rep, customer_type="INDIVIDUAL", full_name="S6 Pep", tax_id="TIN-S06",
            country_risk_tier="HIGH", is_pep=True,
        )
        account = create_account(
            customer["id"], rep,
            product_set=["LOW_PRICED_SECURITIES", "MARGIN", "OPTIONS"],
        )
        review = create_edd_review(
            account["id"], period_start="2026-04-01", period_end="2026-05-01",
            trigger_reason="onboarding",
        )
        begin_edd_review(review["id"])
        completed = complete_edd_review(
            review["id"], "REJECTED", notes="unverifiable funds"
        )
        assert completed["status"] == "REJECTED"

        after = get_account(account["id"])
        assert after["lifecycle_status"] == "DECLINED", (
            f"EDD rejection must decline a PENDING_APPROVAL account, "
            f"got {after['lifecycle_status']}"
        )
        assert after["decline_reason"], "decline_reason must record the EDD rejection"


class TestRepCannotApproveAccount:
    def test_registered_rep_role_denied_on_approve(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target endpoint is
        rejected with `ERR_UNAUTHORIZED_ROLE`."
        PRD §4: `POST /aml/accounts/{id}/approve` is authorized for
        `ComplianceOfficer` only — the opening RegisteredRep cannot approve their own
        account, and the account stays PENDING_APPROVAL.

        Design: Corner/rbac/rep_cannot_approve_account
        """
        ctx = setup_pending_account()
        resp = api_client.approve_account(
            ctx["account"]["id"], make_rep_headers(ctx["rep"]["id"])
        )
        error = validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert error["error_id"] == "ERR_UNAUTHORIZED_ROLE"
        assert resp.status_code == 403
        assert (
            get_account(ctx["account"]["id"])["lifecycle_status"] == "PENDING_APPROVAL"
        )
