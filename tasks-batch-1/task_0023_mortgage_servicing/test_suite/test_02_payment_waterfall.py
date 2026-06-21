"""Payment posting waterfall: standard vs principal-curtailment, late fees,
amount validation, listing."""
from test_helpers import (
    ApiErrorId,
    validate_success,
    validate_error,
    validate_paginated,
    create_loan,
    create_borrower,
    create_escrow_account,
    post_payment,
    set_clock,
    make_loan_servicer_headers,
    setup_borrower_loan_escrow,
    setup_delinquent_loan,
)


class TestPaymentWaterfallDualVariant:

    def test_standard_waterfall_surplus_goes_to_suspense(self, api):
        """PRD §3.2: "Under the STANDARD_WATERFALL strategy the regulatory
        order is: first satisfy accrued_interest_cents; second satisfy the
        principal portion of the oldest unpaid installment, reducing
        principal_balance_cents; third top up the escrow installment by
        escrow_monthly_cents to bring escrow current for the period; fourth
        satisfy the PMI premium for the installment, pmi_monthly_cents;
        fifth pay outstanding late fees, latest-posted-first. After those
        five buckets, any residual amount that is less than one full
        installment short of the next-due posts to the payment's
        suspense_cents bucket; any residual that is at least a full
        installment posts as additional principal curtailment."

        Design: Difficulty/dual_variant_calc/dual_variant_payment_posting_standard_vs_curtailment
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
        create_escrow_account(loan["id"], 480000, 120000, 2)
        # Clock at 2026-02-01: 1 day past next_due (2026-01-31), within grace,
        # so loan is still CURRENT. STANDARD_WATERFALL surplus → suspense.
        set_clock("2026-02-01T00:00:00Z")
        resp = api.post_payment(
            loan["id"],
            {"amount_cents": 300000, "received_at": "2026-02-01T00:00:00Z",
             "posting_strategy": "STANDARD_WATERFALL"},
            make_loan_servicer_headers(),
        )
        payment = validate_success(resp, expected_status=201)
        alloc = payment["allocation"]
        # PRD §3.1 amortization → P*r = 30000000*0.005 = 150000 interest;
        # 179865 - 150000 = 29865 principal. Escrow 50000. PMI 12500.
        # Installment total 242365. Surplus 300000-242365 = 57635 to suspense.
        assert alloc["interest_cents"] == 150000
        assert alloc["principal_cents"] == 29865
        assert alloc["escrow_cents"] == 50000
        assert alloc["pmi_cents"] == 12500
        assert alloc["late_fee_cents"] == 0
        assert alloc["suspense_cents"] == 57635
        assert payment["status"] == "POSTED"


class TestPaymentValidation:

    def test_payment_with_zero_amount_returns_invalid_amount(self, api):
        """PRD §3.2: "The system rejects a remittance whose amount_cents
        is not strictly positive with ERR_INVALID_AMOUNT."

        Design: Corner/validations/validation_payment_zero_amount
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
            with_escrow=False,
        )
        resp = api.post_payment(
            ctx["loan"]["id"],
            {"amount_cents": 0, "received_at": "2026-01-15T00:00:00Z"},
            make_loan_servicer_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT)


class TestPaymentListing:

    def test_list_loan_payments_returns_all_posted(self, api):
        """PRD §2.3: "The response envelope's meta object on list responses
        includes limit, offset, total_count, and has_more, where total_count
        reports the size of the unpaginated result set and has_more is true
        when additional pages remain."

        Design: Corner/endpoints/ep_get_loan_payments_returns_array
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
        post_payment(
            ctx["loan"]["id"], 242365, "2026-01-15T00:00:00Z",
        )
        post_payment(
            ctx["loan"]["id"], 242365, "2026-02-15T00:00:00Z",
        )
        resp = api.list_loan_payments(
            ctx["loan"]["id"], make_loan_servicer_headers(),
        )
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
        assert len(data) == 2
