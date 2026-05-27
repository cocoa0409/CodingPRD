"""Escrow account creation, cushion validation, disbursement scheduling,
scheduled-actions firing, and invariant preservation on cancel."""
from test_helpers import (
    ApiErrorId,
    api_client,
    validate_success,
    validate_error,
    set_clock,
    create_borrower,
    create_loan,
    create_escrow_account_payload,
    create_disbursement_payload,
    post_payment,
    fetch_escrow_account,
    fetch_disbursement,
    make_loan_servicer_headers,
    setup_borrower_loan_escrow,
)


class TestEscrowAccountCreation:

    def test_cushion_default_two_applied_when_omitted(self, api):
        """PRD §3.6: "The escrow account is created by a LoanServicer who
        supplies the projected annual_tax_cents, the projected
        annual_insurance_cents, and optionally cushion_months — the
        permitted cushion in months — which defaults to two."

        Design: Corner/entities/entity_escrow_cushion_default_applied
        """
        set_clock("2026-01-01T00:00:00Z")
        borrower = create_borrower()
        loan = create_loan(
            borrower_id=borrower["id"],
            origination_date="2026-01-01T00:00:00Z",
            original_principal_cents=20000000,
            original_property_value_cents=25000000,
            interest_rate_bps=500,
            term_months=360,
            pmi_monthly_cents=9000,
        )
        # Omit cushion_months — server should default to 2.
        resp = api.create_escrow_account(
            create_escrow_account_payload(
                loan_id=loan["id"], annual_tax_cents=480000,
                annual_insurance_cents=120000, cushion_months=None,
            ),
            make_loan_servicer_headers(),
        )
        escrow = validate_success(resp, expected_status=201)
        assert escrow["cushion_months"] == 2

    def test_cushion_overlimit_returns_error(self, api):
        """PRD §3.6: "The Federal RESPA cap on the cushion is two months;
        the system rejects any value outside the inclusive range zero to
        two with ERR_CUSHION_OVERLIMIT, and the same cap is enforced on
        subsequent updates of the cushion field."

        Design: Corner/entities/entity_escrow_invalid_cushion_returns_overlimit
        """
        set_clock("2026-01-01T00:00:00Z")
        borrower = create_borrower()
        loan = create_loan(
            borrower_id=borrower["id"],
            origination_date="2026-01-01T00:00:00Z",
            original_principal_cents=20000000,
            original_property_value_cents=25000000,
            interest_rate_bps=500,
            term_months=360,
            pmi_monthly_cents=9000,
        )
        resp = api.create_escrow_account(
            create_escrow_account_payload(
                loan_id=loan["id"], annual_tax_cents=480000,
                annual_insurance_cents=120000, cushion_months=3,
            ),
            make_loan_servicer_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_CUSHION_OVERLIMIT)


class TestDisbursementScheduling:

    def test_disbursement_in_past_returns_error(self, api):
        """PRD §3.6: "The scheduled_for must be in the future — strictly
        greater than the simulated current UTC time — and a violation is
        rejected with ERR_DISBURSEMENT_IN_PAST."

        Design: Corner/validations/validation_disbursement_in_past_returns_error
        """
        ctx = setup_borrower_loan_escrow(
            clock_iso="2026-06-01T00:00:00Z",
            origination_date="2026-06-01T00:00:00Z",
        )
        resp = api.create_disbursement(
            ctx["escrow_account"]["id"],
            create_disbursement_payload(
                kind="TAX",
                amount_cents=480000,
                scheduled_for="2026-05-01T00:00:00Z",  # in the past.
            ),
            make_loan_servicer_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_IN_PAST)


class TestDisbursementClockFires:

    def test_clock_advance_fires_scheduled_disbursement_when_balance_sufficient(self, api):
        """PRD §3.6: "When the simulated current UTC time reaches or passes
        the scheduled_for, the system evaluates the escrow account's
        balance_cents: if the balance is at least the disbursement's
        amount_cents, the disbursement transitions to PAID, its paid_at is
        set to the current UTC time, the account's balance_cents is reduced
        by the disbursement amount, and the account's version is
        incremented."

        Design: Corner/cross_cutting_complexity_layers/layer_scheduled_action_disbursement_fires_on_clock
        """
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_borrower_loan_escrow(
            clock_iso="2026-01-01T00:00:00Z",
            origination_date="2026-01-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        # Post one full installment to build escrow balance to 50000.
        post_payment(ctx["loan"]["id"], 242365, "2026-01-15T00:00:00Z")
        disb = validate_success(api.create_disbursement(
            ctx["escrow_account"]["id"],
            create_disbursement_payload(
                kind="INSURANCE", amount_cents=30000,
                scheduled_for="2026-06-01T00:00:00Z",
            ),
            make_loan_servicer_headers(),
        ), expected_status=201)
        # Advance past scheduled_for.
        set_clock("2026-06-02T00:00:00Z")
        disb_after = fetch_disbursement(disb["id"])
        assert disb_after["status"] == "PAID"
        esc_after = fetch_escrow_account(ctx["escrow_account"]["id"])
        # Balance 50000 - 30000 = 20000.
        assert esc_after["balance_cents"] == 20000

    def test_disbursement_with_insufficient_balance_transitions_to_failed(self, api):
        """PRD §3.6: "If the balance is strictly less than the disbursement
        amount, the disbursement transitions to FAILED, its failure_reason
        is set to INSUFFICIENT_FUNDS, the balance is left untouched, and
        the account's version is still incremented to record that the
        disbursement was evaluated."

        Design: Difficulty/cross_entity_state_dependency/cross_escrowdisbursement_escrowaccount_balance_dependency
        """
        ctx = setup_borrower_loan_escrow(
            clock_iso="2026-01-01T00:00:00Z",
            origination_date="2026-01-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        disb = validate_success(api.create_disbursement(
            ctx["escrow_account"]["id"],
            create_disbursement_payload(
                kind="TAX", amount_cents=480000,
                scheduled_for="2026-02-01T00:00:00Z",
            ),
            make_loan_servicer_headers(),
        ), expected_status=201)
        # No payment posted yet → balance is still 0 (well below 480000).
        set_clock("2026-02-02T00:00:00Z")
        disb_after = fetch_disbursement(disb["id"])
        assert disb_after["status"] == "FAILED"
        assert disb_after["failure_reason"] == "INSUFFICIENT_FUNDS"


class TestDisbursementCancel:

    def test_cancel_scheduled_disbursement_preserves_escrow_balance(self, api):
        """PRD §3.6: "A scheduled disbursement may instead be cancelled
        explicitly by a LoanServicer, moving it to CANCELLED, or cancelled
        implicitly as a cascade from a loan reaching PAID_OFF. The terminal
        statuses are PAID, FAILED, and CANCELLED."

        Design: Difficulty/compensating_invariant/invariant_disbursement_cancel_preserves_escrow_balance
        """
        ctx = setup_borrower_loan_escrow(
            clock_iso="2025-12-01T00:00:00Z",
            origination_date="2025-12-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        set_clock("2026-01-01T00:00:00Z")
        # One full installment → escrow balance = 50000.
        post_payment(ctx["loan"]["id"], 242365, "2026-01-01T00:00:00Z")
        balance_pre = fetch_escrow_account(
            ctx["escrow_account"]["id"]
        )["balance_cents"]
        assert balance_pre == 50000
        disb = validate_success(api.create_disbursement(
            ctx["escrow_account"]["id"],
            create_disbursement_payload(
                kind="TAX", amount_cents=30000,
                scheduled_for="2026-06-01T00:00:00Z",
            ),
            make_loan_servicer_headers(),
        ), expected_status=201)
        # Cancel it.
        validate_success(api.cancel_disbursement(
            disb["id"], make_loan_servicer_headers(),
        ))
        disb_after = fetch_disbursement(disb["id"])
        assert disb_after["status"] == "CANCELLED"
        balance_after = fetch_escrow_account(
            ctx["escrow_account"]["id"]
        )["balance_cents"]
        # Cancel does not touch the balance.
        assert balance_after == 50000
