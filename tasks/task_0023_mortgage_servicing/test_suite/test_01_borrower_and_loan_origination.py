"""Borrower creation, loan origination, amortization math, listing, and
common-resource invariants."""
from test_helpers import (
    api_client,
    ApiErrorId,
    NON_EXISTENT_UUID,
    validate_success,
    validate_error,
    validate_paginated,
    create_borrower_payload,
    create_loan_payload,
    create_borrower,
    create_loan,
    set_clock,
    make_loan_servicer_headers,
    assert_loan,
)


class TestLoanCreation:

    def test_create_loan_returns_201_with_computed_fields(self, api):
        """PRD §3.1: "The scheduled monthly principal-and-interest in cents
        is then P multiplied by r multiplied by one-plus-r raised to the n,
        divided by one-plus-r raised to the n minus one, with the final
        result rounded half-up to a whole number of cents."
        PRD §3.1: "Immediately after origination the loan's principal_balance_cents
        is set to original_principal_cents, the accrued_interest_cents is set
        to zero, the next_due_date is set to thirty calendar days after the
        origination_date, the lifecycle status is set to CURRENT, and the
        loan's version is set to 1."

        Design: Corner/entities/entity_loan_creation_returns_201_with_computed_fields
        """
        borrower = create_borrower()
        payload = create_loan_payload(
            borrower_id=borrower["id"],
            origination_date="2026-01-01T00:00:00Z",
            original_principal_cents=20000000,
            original_property_value_cents=25000000,
            interest_rate_bps=500,
            term_months=360,
            pmi_monthly_cents=9000,
        )
        resp = api.create_loan(payload, make_loan_servicer_headers())
        loan = validate_success(resp, expected_status=201)
        assert_loan(loan)
        assert loan["scheduled_monthly_pi_cents"] == 107364, (
            f"P=20M @ 5%/360 amortization expects 107364, got "
            f"{loan['scheduled_monthly_pi_cents']}"
        )
        assert loan["principal_balance_cents"] == 20000000
        assert loan["status"] == "CURRENT"
        assert loan["version"] == 1

    def test_get_loan_returns_stored_data(self, api):
        """PRD §3.1: "the lifecycle status is set to CURRENT" — a freshly
        originated loan is retrievable in CURRENT status with its original
        principal preserved.

        Design: Corner/entities/entity_loan_get_returns_stored_data
        """
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
        resp = api.get_loan(loan["id"], make_loan_servicer_headers())
        fetched = validate_success(resp)
        assert fetched["status"] == "CURRENT"
        assert fetched["original_principal_cents"] == 20000000

    def test_list_loans_paginates(self, api):
        """PRD §2.3: "List endpoints accept two optional query parameters.
        The limit parameter caps the number of items returned in a single
        page; it defaults to 10, with a minimum of 1 and a maximum of 100.
        The offset parameter specifies the number of items to skip and
        defaults to 0."
        PRD §2.3: "The response envelope's meta object on list responses
        includes limit, offset, total_count, and has_more, where total_count
        reports the size of the unpaginated result set and has_more is true
        when additional pages remain."

        Design: Corner/entities/entity_loan_list_pagination
        """
        borrower = create_borrower()
        create_loan(
            borrower_id=borrower["id"],
            original_principal_cents=20000000,
            original_property_value_cents=25000000,
            interest_rate_bps=500,
            term_months=360,
            pmi_monthly_cents=9000,
        )
        create_loan(
            borrower_id=borrower["id"],
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        resp = api.list_loans(
            make_loan_servicer_headers(),
            params={"borrower_id": borrower["id"], "limit": 1, "offset": 0},
        )
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert len(data) == 1

    def test_get_nonexistent_loan_returns_resource_not_found(self, api):
        """PRD §2.6: "The first identifier that does not resolve to an
        existing row causes the request to be rejected with
        ERR_RESOURCE_NOT_FOUND."

        Design: Corner/entities/entity_loan_get_nonexistent_returns_404
        """
        resp = api.get_loan(NON_EXISTENT_UUID, make_loan_servicer_headers())
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)

    def test_create_loan_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.9: "Generic request-shape validation (required input
        fields present and well-typed) sits last at priority fifteen with
        ERR_INVALID_REQUEST; this last bucket is the catch-all for
        malformed payloads that did not trigger any earlier check."

        Design: Corner/entities/entity_loan_missing_required_field_returns_invalid_request
        """
        borrower = create_borrower()
        # Omits original_principal_cents (a required input per PRD §3.1).
        payload = {
            "borrower_id": borrower["id"],
            "origination_date": "2026-01-01T00:00:00Z",
            "original_property_value_cents": 25000000,
            "interest_rate_bps": 500,
            "term_months": 360,
            "pmi_monthly_cents": 9000,
        }
        resp = api.create_loan(payload, make_loan_servicer_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_loan_with_unknown_borrower_returns_fk_not_found(self, api):
        """PRD §2.6: "After every path identifier resolves, foreign-key
        references inside the request body — borrower_id, loan_id,
        escrow_account_id, foreclosure_case_id — are resolved next; any
        unresolved body reference is rejected with ERR_FK_NOT_FOUND."

        Design: Corner/entities/entity_loan_fk_borrower_not_found
        """
        payload = create_loan_payload(
            borrower_id=NON_EXISTENT_UUID,
            original_principal_cents=20000000,
            original_property_value_cents=25000000,
            interest_rate_bps=500,
            term_months=360,
            pmi_monthly_cents=9000,
        )
        resp = api.create_loan(payload, make_loan_servicer_headers())
        validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND)


class TestAmortization:

    def test_amortization_three_inputs_nonlinear_300k_6pct_360mo(self, api):
        """PRD §3.1: "The scheduled monthly principal-and-interest in cents
        is then P multiplied by r multiplied by one-plus-r raised to the n,
        divided by one-plus-r raised to the n minus one, with the final
        result rounded half-up to a whole number of cents. The intermediate
        compound-interest factor is never itself rounded."

        Design: Difficulty/combinatorial_formula/combinatorial_amortization_three_inputs_nonlinear
        """
        borrower = create_borrower()
        payload = create_loan_payload(
            borrower_id=borrower["id"],
            origination_date="2026-01-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        resp = api.create_loan(payload, make_loan_servicer_headers())
        loan = validate_success(resp, expected_status=201)
        assert loan["scheduled_monthly_pi_cents"] == 179865
        assert loan["principal_balance_cents"] == 30000000
        assert loan["status"] == "CURRENT"

    def test_amortization_zero_rate_edge_falls_back_to_pn(self, api):
        """PRD §3.1: "The edge case of a zero monthly rate (where the
        closed-form has a division-by-zero) is handled by reducing the
        formula to the original principal divided by the number of months,
        rounded half-up to a whole number of cents."

        Design: Corner/calculations/calc_amortization_zero_rate_edge
        """
        borrower = create_borrower()
        payload = create_loan_payload(
            borrower_id=borrower["id"],
            origination_date="2026-01-01T00:00:00Z",
            original_principal_cents=12000000,
            original_property_value_cents=30000000,
            interest_rate_bps=0,
            term_months=120,
            pmi_monthly_cents=0,
        )
        resp = api.create_loan(payload, make_loan_servicer_headers())
        loan = validate_success(resp, expected_status=201)
        assert loan["scheduled_monthly_pi_cents"] == 100000


class TestDerivedFieldReconciliation:

    def test_total_monthly_payment_recomputes_after_escrow_creation(self, api):
        """PRD §3.6: "as a side effect of escrow-account creation the loan's
        escrow_monthly_cents is initialized to the round-half-up of the sum
        of annual_tax_cents and annual_insurance_cents divided by twelve,
        the loan's total_monthly_payment_cents is recomputed to include the
        new escrow installment, and the loan's version is incremented."

        Design: Corner/cross_cutting_complexity_layers/layer_derived_field_total_monthly_payment
        """
        set_clock("2025-01-01T00:00:00Z")
        borrower = create_borrower()
        loan = create_loan(
            borrower_id=borrower["id"],
            origination_date="2025-01-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        api_client.create_escrow_account(
            {"loan_id": loan["id"], "annual_tax_cents": 480000,
             "annual_insurance_cents": 120000, "cushion_months": 2},
            make_loan_servicer_headers(),
        )
        resp = api.get_loan(loan["id"], make_loan_servicer_headers())
        refreshed = validate_success(resp)
        # round_half_up((480000+120000)/12) = 50000.
        assert refreshed["escrow_monthly_cents"] == 50000
        # 179865 P&I + 50000 escrow + 12500 PMI.
        assert refreshed["total_monthly_payment_cents"] == 242365


class TestImmediateConsistency:

    def test_payment_allocation_visible_in_same_response(self, api):
        """PRD §3.2: "The result of a posting is a Payment row whose
        allocation object captures the breakdown across six buckets —
        interest_cents, principal_cents, escrow_cents, pmi_cents,
        late_fee_cents, and suspense_cents — and whose status is POSTED
        when at least one full installment cleared and SUSPENSE when the
        remittance landed entirely in the suspense bucket because it was
        less than what was needed to advance the installment."

        Design: Corner/consistency_model/consistency_immediate_payment_visible_in_same_response
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
        api.create_escrow_account(
            {"loan_id": loan["id"], "annual_tax_cents": 480000,
             "annual_insurance_cents": 120000, "cushion_months": 2},
            make_loan_servicer_headers(),
        )
        resp = api.post_payment(
            loan["id"],
            {"amount_cents": 242365, "received_at": "2026-01-15T00:00:00Z"},
            make_loan_servicer_headers(),
        )
        payment = validate_success(resp, expected_status=201)
        assert payment["status"] == "POSTED"
        alloc = payment["allocation"]
        # PRD §3.2 STANDARD waterfall: interest first (30000000 * 0.005 = 150000),
        # then principal (179865 - 150000 = 29865), then escrow 50000, PMI 12500.
        assert alloc["principal_cents"] == 29865
        assert alloc["interest_cents"] == 150000
        assert alloc["escrow_cents"] == 50000
        assert alloc["pmi_cents"] == 12500
