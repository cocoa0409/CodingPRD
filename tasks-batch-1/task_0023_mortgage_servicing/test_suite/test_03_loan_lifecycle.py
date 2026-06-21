"""Loan lifecycle: grace, DELINQUENT/CURRENT/PAID_OFF transitions, payoff
cascade to scheduled disbursements."""
from test_helpers import (
    ApiErrorId,
    validate_success,
    validate_error,
    set_clock,
    create_borrower,
    create_loan,
    create_escrow_account,
    post_payment,
    fetch_loan,
    fetch_disbursement,
    make_loan_servicer_headers,
    setup_delinquent_loan,
    setup_loan_paid_off_with_scheduled_disbursement,
    setup_borrower_loan_escrow,
)


class TestGraceBoundary:

    def test_grace_boundary_exact_15_days_stays_current(self, api):
        """PRD §3.3: "The delinquency boundary is fifteen days. When the
        simulated current UTC time is set to an instant more than fifteen
        days past a loan's next_due_date and no payment has posted to cure
        the past-due amount, the loan auto-transitions from CURRENT to
        DELINQUENT and its version is incremented."

        Design: Corner/cross_cutting_complexity_layers/layer_threshold_grace_boundary_exact_15_days
        """
        set_clock("2026-01-01T00:00:00Z")
        borrower = create_borrower()
        loan = create_loan(
            borrower_id=borrower["id"],
            origination_date="2026-01-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        # next_due_date = 2026-01-31. Clock at 2026-02-15: days_past_due = 15,
        # which is NOT > 15, so the loan stays CURRENT per PRD §3.3.
        set_clock("2026-02-15T00:00:00Z")
        refreshed = fetch_loan(loan["id"])
        assert refreshed["status"] == "CURRENT"
        assert refreshed["days_past_due"] == 15

    def test_clock_advance_past_grace_transitions_to_delinquent(self, api):
        """PRD §3.3: "When the simulated current UTC time is set to an
        instant more than fifteen days past a loan's next_due_date and no
        payment has posted to cure the past-due amount, the loan
        auto-transitions from CURRENT to DELINQUENT and its version is
        incremented. The transition is fired by the clock-advance
        capability, not by any borrower-initiated request, and it fires on
        every loan that newly satisfies the precondition when the clock
        moves forward."

        Design: Corner/state_machines/sm_clock_drives_current_to_delinquent_after_grace
        """
        set_clock("2026-01-01T00:00:00Z")
        borrower = create_borrower()
        loan = create_loan(
            borrower_id=borrower["id"],
            origination_date="2026-01-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        # next_due_date 2026-01-31; +16 days = 2026-02-16.
        set_clock("2026-02-16T00:00:00Z")
        refreshed = fetch_loan(loan["id"])
        assert refreshed["status"] == "DELINQUENT"


class TestCureFromDelinquent:

    def test_full_curing_payment_returns_delinquent_loan_to_current(self, api):
        """PRD §3.2: "When the loan was in DELINQUENT status and the
        allocation drives days_past_due to zero, the loan transitions to
        CURRENT and the next due date advances accordingly."

        Design: Corner/state_machines/sm_loan_cure_returns_delinquent_to_current
        """
        ctx = setup_delinquent_loan(
            clock_iso="2026-01-01T00:00:00Z",
            after_grace_iso="2026-02-20T00:00:00Z",
            origination_date="2026-01-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        # Full installment 242365 cures days_past_due to 0.
        post_payment(ctx["loan"]["id"], 242365, "2026-02-20T00:00:00Z")
        refreshed = fetch_loan(ctx["loan"]["id"])
        assert refreshed["status"] == "CURRENT"
        assert refreshed["days_past_due"] == 0


class TestPayoffCascade:

    def test_payoff_cancels_scheduled_disbursements_three_hops(self, api):
        """PRD §3.2: "When the remittance is at least the sum of
        principal_balance_cents, accrued_interest_cents, and any outstanding
        fees — fully retiring the obligation — and the loan was in CURRENT
        status, the loan transitions to PAID_OFF (a terminal state), the
        loan's pmi_status is set to AUTO_TERMINATED, and every
        EscrowDisbursement still in SCHEDULED status for this loan's escrow
        account is cascaded to CANCELLED so no further outflows fire against
        an account whose loan no longer exists in a serviceable form."

        Design: Difficulty/transitive_cascade/cascade_payoff_loan_cancels_disbursements_three_hops
        """
        ctx = setup_loan_paid_off_with_scheduled_disbursement(
            clock_iso="2025-12-01T00:00:00Z",
            original_principal_cents=12000000,
            disbursement_amount_cents=360000,
            disbursement_scheduled_for="2026-04-15T00:00:00Z",
        )
        # Pay off the entire principal in one shot while loan is CURRENT.
        post_payment(
            ctx["loan"]["id"], 12000000, "2025-12-15T00:00:00Z",
        )
        loan_after = fetch_loan(ctx["loan"]["id"])
        assert loan_after["status"] == "PAID_OFF"
        assert loan_after["principal_balance_cents"] == 0
        disb_after = fetch_disbursement(ctx["disbursement"]["id"])
        assert disb_after["status"] == "CANCELLED"

    def test_paid_off_loan_rejects_further_payment(self, api):
        """PRD §3.2: "the loan transitions to PAID_OFF (a terminal state)".
        PRD §2.9: "State-transition admissibility is evaluated fifth,
        producing ERR_INVALID_STATE when the resource is not in a state
        from which the requested transition is permitted."

        Design: Corner/state_machines/sm_loan_terminal_paid_off_locked
        """
        set_clock("2025-12-01T00:00:00Z")
        borrower = create_borrower()
        loan = create_loan(
            borrower_id=borrower["id"],
            origination_date="2025-12-01T00:00:00Z",
            original_principal_cents=12000000,
            original_property_value_cents=30000000,
            interest_rate_bps=0,
            term_months=120,
            pmi_monthly_cents=0,
        )
        # Full payoff (no escrow, no PMI, no accrued interest yet).
        post_payment(loan["id"], 12000000, "2025-12-15T00:00:00Z")
        loan_after = fetch_loan(loan["id"])
        assert loan_after["status"] == "PAID_OFF"
        # Any further payment must be rejected.
        resp = api.post_payment(
            loan["id"],
            {"amount_cents": 100000, "received_at": "2025-12-16T00:00:00Z"},
            make_loan_servicer_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
