"""Authentication, authorization, and ownership-based RBAC across roles."""
from test_helpers import (
    ApiErrorId,
    validate_error,
    validate_success,
    create_borrower,
    create_loan,
    set_clock,
    create_loan_payload,
    create_pmi_removal_request_payload,
    make_loan_servicer_headers,
    make_compliance_officer_headers,
    make_borrower_headers,
    make_anonymous_headers,
    setup_pmi_request_pending,
)


class TestAuthentication:

    def test_missing_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request to the API must carry two mandatory
        headers: X-User-ID, identifying the acting principal, and
        X-User-Role, identifying their role. The system recognizes exactly
        three roles, spelled LoanServicer, ComplianceOfficer, and Borrower.
        A request that omits either header is rejected with
        ERR_UNAUTHENTICATED; a request whose role is not permitted for
        the endpoint it targets is rejected with ERR_UNAUTHORIZED."

        Design: Corner/errors/err_unauthenticated_missing_user_id
        """
        borrower = create_borrower()
        payload = create_loan_payload(
            borrower_id=borrower["id"],
            original_principal_cents=20000000,
            original_property_value_cents=25000000,
            interest_rate_bps=500,
            term_months=360,
            pmi_monthly_cents=9000,
        )
        resp = api.create_loan(payload, make_anonymous_headers())
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestAuthorization:

    def test_borrower_cannot_originate_loan(self, api):
        """PRD §2.1: "LoanServicer operators originate loans, post payments
        on behalf of borrowers, manage forbearance and foreclosure
        workflows, schedule escrow disbursements, and run escrow analyses."
        PRD §2.1: "a request whose role is not permitted for the endpoint
        it targets is rejected with ERR_UNAUTHORIZED."

        Design: Corner/errors/err_unauthorized_borrower_attempts_originate_loan
        """
        borrower = create_borrower()
        payload = create_loan_payload(
            borrower_id=borrower["id"],
            original_principal_cents=20000000,
            original_property_value_cents=25000000,
            interest_rate_bps=500,
            term_months=360,
            pmi_monthly_cents=9000,
        )
        resp = api.create_loan(payload, make_borrower_headers(borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_compliance_officer_cannot_originate_loan(self, api):
        """PRD §2.1: "A ComplianceOfficer is the sole role authorized to
        record a decision on a PMI removal request; the role is otherwise
        read-only across loans and payments and may not originate,
        foreclose, or post payments."

        Design: Corner/rbac/rbac_complianceofficer_cannot_originate
        """
        borrower = create_borrower()
        payload = create_loan_payload(
            borrower_id=borrower["id"],
            original_principal_cents=20000000,
            original_property_value_cents=25000000,
            interest_rate_bps=500,
            term_months=360,
            pmi_monthly_cents=9000,
        )
        resp = api.create_loan(payload, make_compliance_officer_headers())
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_loan_servicer_cannot_decide_pmi(self, api):
        """PRD §2.1: "A ComplianceOfficer is the sole role authorized to
        record a decision on a PMI removal request".

        Design: Corner/rbac/rbac_loanservicer_cannot_decide_pmi
        """
        ctx = setup_pmi_request_pending(
            clock_iso="2026-01-01T00:00:00Z",
            original_principal_cents=27000000,
            original_property_value_cents=40000000,
            pmi_monthly_cents=13000,
            interest_rate_bps=500,
            origination_date="2026-01-01T00:00:00Z",
        )
        resp = api.decide_pmi_removal_request(
            ctx["pmi_request"]["id"], make_loan_servicer_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestBorrowerOwnership:

    def test_borrower_can_get_own_loan(self, api):
        """PRD §2.1: "When X-User-Role is Borrower, X-User-ID is the id of
        the acting Borrower row, and ownership checks on any resource that
        ultimately references a Borrower compare the resource's borrower
        foreign-key chain to X-User-ID. Concretely, a Borrower may read
        and act on a Loan only when the loan's borrower_id equals
        X-User-ID".

        Design: Corner/rbac/rbac_borrower_can_get_own_loan
        """
        borrower = create_borrower()
        loan = create_loan(
            borrower_id=borrower["id"],
            original_principal_cents=20000000,
            original_property_value_cents=25000000,
            interest_rate_bps=500,
            term_months=360,
            pmi_monthly_cents=9000,
        )
        resp = api.get_loan(loan["id"], make_borrower_headers(borrower["id"]))
        fetched = validate_success(resp)
        assert fetched["status"] == "CURRENT"
        assert fetched["id"] == loan["id"]

    def test_borrower_cannot_read_other_borrowers_loan(self, api):
        """PRD §2.1: "a Borrower may read and act on a Loan only when the
        loan's borrower_id equals X-User-ID; the borrower may read and act
        on Payment, EscrowAccount, EscrowDisbursement, EscrowAnalysis,
        ForbearancePlan, ForeclosureCase, MediationSession, and
        PMIRemovalRequest rows only when the chain of foreign keys from the
        row back to its parent loan resolves to a loan whose borrower_id
        equals X-User-ID. Any mismatch is rejected with ERR_UNAUTHORIZED."

        Design: Corner/rbac/rbac_borrower_cannot_read_other_borrowers_loan
        """
        borrower_a = create_borrower(email="a-borrower@example.com")
        borrower_b = create_borrower(email="b-borrower@example.com")
        loan_of_b = create_loan(
            borrower_id=borrower_b["id"],
            original_principal_cents=20000000,
            original_property_value_cents=25000000,
            interest_rate_bps=500,
            term_months=360,
            pmi_monthly_cents=9000,
        )
        # Borrower A tries to read B's loan.
        resp = api.get_loan(
            loan_of_b["id"], make_borrower_headers(borrower_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
