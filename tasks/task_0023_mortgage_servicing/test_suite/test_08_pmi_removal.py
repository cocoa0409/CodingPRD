"""PMI removal: LTV boundary, auto-termination, clean-history check,
denial precedence, decide on terminal state, delinquency cascade blocks."""
from test_helpers import (
    ApiErrorId,
    validate_success,
    validate_error,
    set_clock,
    create_borrower,
    create_loan,
    create_escrow_account,
    create_pmi_removal_request_payload,
    post_payment,
    fetch_loan,
    fetch_pmi_request,
    make_loan_servicer_headers,
    make_compliance_officer_headers,
    setup_pmi_request_pending,
    setup_borrower_loan_escrow,
)


class TestPmiLtvBoundary:

    def test_pmi_denied_when_ltv_at_exact_8000_bps(self, api):
        """PRD §3.8: "The borrower-requested path requires the
        loan-to-value in basis points to be strictly less than eight
        thousand (less than eighty percent) and additionally requires a
        clean payment history over the trailing twelve months."
        PRD §3.8: "The denial reason follows a strict first-match
        precedence: a loan whose status is not in the set CURRENT or
        REINSTATED yields IN_DELINQUENCY; otherwise a loan-to-value in
        basis points at or above eight thousand yields LTV_TOO_HIGH;
        otherwise a payment history that is not clean yields
        PAYMENT_HISTORY_NOT_CLEAN."

        Design: Difficulty/boundary_precision_check/boundary_pmi_ltv_exact_8000_bps_denied
        """
        # P=32000000, V=40000000 → LTV = round_half_up(32000000*10000/40000000) = 8000.
        ctx = setup_pmi_request_pending(
            clock_iso="2025-06-01T00:00:00Z",
            original_principal_cents=32000000,
            original_property_value_cents=40000000,
            pmi_monthly_cents=13000,
            origination_date="2025-06-01T00:00:00Z",
        )
        pmi = fetch_pmi_request(ctx["pmi_request"]["id"])
        assert pmi["computed_ltv_bps"] == 8000
        resp = api.decide_pmi_removal_request(
            pmi["id"], make_compliance_officer_headers(),
        )
        decided = validate_success(resp)
        assert decided["status"] == "DENIED"
        assert decided["denial_reason"] == "LTV_TOO_HIGH"


class TestPmiAutoTerminationPath:

    def test_ltv_below_7800_approved_without_history_check(self, api):
        """PRD §3.8: "The automatic-termination path, reflecting the
        Federal HPA threshold, requires the loan-to-value in basis points
        to be strictly less than seven thousand eight hundred (less than
        seventy-eight percent) and applies unconditionally regardless of
        payment history."

        Design: Corner/calculations/calc_pmi_eligibility_auto_termination_path
        """
        # P=31196000, V=40000000 → 7799 bps.
        ctx = setup_pmi_request_pending(
            clock_iso="2026-01-01T00:00:00Z",
            original_principal_cents=31196000,
            original_property_value_cents=40000000,
            pmi_monthly_cents=13000,
            interest_rate_bps=500,
            origination_date="2026-01-01T00:00:00Z",
        )
        pmi = fetch_pmi_request(ctx["pmi_request"]["id"])
        assert pmi["computed_ltv_bps"] == 7799
        resp = api.decide_pmi_removal_request(
            pmi["id"], make_compliance_officer_headers(),
        )
        decided = validate_success(resp)
        assert decided["status"] == "APPROVED"


class TestPmiHistoryNotClean:

    def test_pmi_denied_when_payment_history_has_suspense(self, api):
        """PRD §3.8: "The clean-payment-history check over the trailing
        twelve months is satisfied when there is no Payment row whose
        status is SUSPENSE in that window and there is no day in the
        trailing twelve months on which the loan's days_past_due exceeded
        thirty."
        PRD §3.8: "otherwise a payment history that is not clean yields
        PAYMENT_HISTORY_NOT_CLEAN. The first matching condition wins and
        the request is denied with that reason"

        Design: Corner/validations/validation_pmi_history_not_clean
        """
        set_clock("2026-01-01T00:00:00Z")
        borrower = create_borrower()
        # P=31600000, V=40000000 → LTV = 7900 (in [7800, 8000)).
        loan = create_loan(
            borrower_id=borrower["id"],
            origination_date="2026-01-01T00:00:00Z",
            original_principal_cents=31600000,
            original_property_value_cents=40000000,
            interest_rate_bps=500,
            term_months=360,
            pmi_monthly_cents=13000,
        )
        create_escrow_account(loan["id"], 480000, 120000, 2)
        # Post 50000 — far below one full installment — so it lands in SUSPENSE.
        # Advance clock so the SUSPENSE payment falls inside the trailing-12
        # window evaluated at the PMI submission/decide time.
        set_clock("2026-01-10T00:00:00Z")
        post_payment(loan["id"], 50000, "2026-01-10T00:00:00Z")
        set_clock("2026-02-01T00:00:00Z")
        pmi_resp = validate_success(api.create_pmi_removal_request(
            create_pmi_removal_request_payload(loan_id=loan["id"]),
            make_loan_servicer_headers(),
        ), expected_status=201)
        assert pmi_resp["computed_ltv_bps"] == 7900
        resp = api.decide_pmi_removal_request(
            pmi_resp["id"], make_compliance_officer_headers(),
        )
        decided = validate_success(resp)
        assert decided["status"] == "DENIED"
        assert decided["denial_reason"] == "PAYMENT_HISTORY_NOT_CLEAN"


class TestPmiDelinquencyCascade:

    def test_clock_drives_delinquency_then_pmi_denied_with_in_delinquency(self, api):
        """PRD §3.3: "When the simulated current UTC time is set to an
        instant more than fifteen days past a loan's next_due_date and no
        payment has posted to cure the past-due amount, the loan
        auto-transitions from CURRENT to DELINQUENT and its version is
        incremented."
        PRD §3.8: "The denial reason follows a strict first-match
        precedence: a loan whose status is not in the set CURRENT or
        REINSTATED yields IN_DELINQUENCY".

        Design: Difficulty/transitive_cascade/cascade_clock_advance_drives_delinquency_then_pmi_pending_blocks
        """
        set_clock("2025-06-01T00:00:00Z")
        borrower = create_borrower()
        loan = create_loan(
            borrower_id=borrower["id"],
            origination_date="2025-06-01T00:00:00Z",
            original_principal_cents=28000000,
            original_property_value_cents=40000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=11000,
        )
        # Submit PMI removal request while loan is CURRENT.
        pmi_req = validate_success(api.create_pmi_removal_request(
            create_pmi_removal_request_payload(loan_id=loan["id"]),
            make_loan_servicer_headers(),
        ), expected_status=201)
        # Advance clock so the loan auto-transitions to DELINQUENT.
        set_clock("2025-08-15T00:00:00Z")
        loan_after = fetch_loan(loan["id"])
        assert loan_after["status"] == "DELINQUENT"
        # Decide PMI — should DENY with IN_DELINQUENCY (state check wins).
        resp = api.decide_pmi_removal_request(
            pmi_req["id"], make_compliance_officer_headers(),
        )
        decided = validate_success(resp)
        assert decided["status"] == "DENIED"
        assert decided["denial_reason"] == "IN_DELINQUENCY"


class TestPmiTerminalLockdown:

    def test_decide_on_already_denied_request_returns_invalid_state(self, api):
        """PRD §3.8: "Decision is permitted only on a request still in
        PENDING; a decision request against a request already in a terminal
        status is rejected with ERR_INVALID_STATE."

        Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_business_fiscal_pmi_decide
        """
        # P=32000000, V=40000000 → LTV = 8000 → first decide DENIED.
        ctx = setup_pmi_request_pending(
            clock_iso="2025-06-01T00:00:00Z",
            original_principal_cents=32000000,
            original_property_value_cents=40000000,
            pmi_monthly_cents=13000,
            origination_date="2025-06-01T00:00:00Z",
        )
        first = validate_success(api.decide_pmi_removal_request(
            ctx["pmi_request"]["id"], make_compliance_officer_headers(),
        ))
        assert first["status"] == "DENIED"
        # Second decide on already-DENIED request.
        resp = api.decide_pmi_removal_request(
            ctx["pmi_request"]["id"], make_compliance_officer_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
