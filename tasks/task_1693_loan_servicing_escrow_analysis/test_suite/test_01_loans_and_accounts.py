"""Loan boarding, escrow account setup, and loan terminal transitions."""
from test_helpers import (
    CO1,
    EA1,
    ApiErrorId,
    DEFAULT_CLOCK_UTC,
    assert_balance_conservation,
    assert_loan,
    create_active_bare_loan,
    create_line_item_payload,
    create_loan_payload,
    create_onboarding_loan,
    create_verified_payee,
    file_error_case,
    get_account,
    get_ledger,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    setup_account_with_scheduled_disbursement,
    setup_active_account,
    setup_released_disbursement,
    validate_error,
    validate_paginated,
    validate_success,
)

ABSENT_UUID = "00000000-0000-4000-8000-000000000000"


class TestLoanCreation:
    def test_create_loan_applies_defaults_and_initial_state(self, api):
        """PRD: "A `ComplianceOfficer` boards a loan by supplying `loan_number`
        (unique across all loans — a duplicate is rejected with
        `ERR_DUPLICATE_LOAN_NUMBER`), `borrower_name`, `principal_balance_cents`,
        `monthly_pi_cents` (the principal-plus-interest portion only, excluding
        escrow), `closing_date` as an ISO date, and optionally `escrow_required`,
        which defaults to true."
        PRD: "A new loan starts in `ONBOARDING`"

        Design: Corner/entities/create_loan_success_defaults
        """
        resp = api.create_loan(
            create_loan_payload(loan_number="LN-ENT-1", borrower_name="Ed Ent"),
            CO1)
        loan = validate_success(resp, 201)
        assert_loan(loan)
        assert loan["status"] == "ONBOARDING", "A new loan starts in ONBOARDING"
        assert loan["escrow_required"] is True, "escrow_required defaults to true"
        assert is_valid_uuid(loan["id"]), "id is a server-minted UUID"
        assert is_iso8601_timestamp(loan["created_at"])
        assert loan["created_at"].startswith("2026-08-01T00:00:00"), (
            "created_at comes from the logical clock, which reads "
            f"{DEFAULT_CLOCK_UTC} before any set call; got {loan['created_at']}")

        fetched = validate_success(api.get_loan(loan["id"], EA1), 200)
        assert fetched["status"] == "ONBOARDING"
        assert fetched["escrow_required"] is True

    def test_create_loan_missing_loan_number_rejected(self, api):
        """PRD: "then request shape — required fields present, enum members
        valid, dates well-formed ISO (`ERR_INVALID_REQUEST`, HTTP 400)"
        PRD: "A `ComplianceOfficer` boards a loan by supplying `loan_number`"

        Design: Corner/entities/create_loan_missing_required_returns_invalid_request
        """
        payload = create_loan_payload(borrower_name="No Number")
        del payload["loan_number"]
        resp = api.create_loan(payload, CO1)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        loans, meta = validate_paginated(api.list_loans(CO1))
        assert loans == [] and meta["total_count"] == 0, (
            "no loan may be created when a required field is missing")

    def test_get_loan_absent_id_returns_not_found(self, api):
        """PRD: "then path identifier existence, resolved left-to-right along
        the URL so the leftmost nonexistent id is the one reported
        (`ERR_NOT_FOUND`, HTTP 404)"

        Design: Corner/entities/get_loan_not_found_returns_404
        """
        resp = api.get_loan(ABSENT_UUID, CO1)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestEscrowAccountCreation:
    def test_computed_fields_in_request_body_silently_ignored(self, api):
        """PRD: "then request shape — required fields present, enum members
        valid, dates well-formed ISO (`ERR_INVALID_REQUEST`, HTTP 400), with
        unknown body fields ignored silently rather than rejected"
        PRD: "The account is born with `account_status` `SETUP`, `hold_status`
        `NONE`, `balance_cents` 0, and `target_cushion_cents` 0"

        Design: Corner/entities/escrow_account_create_extra_field_ignored
        """
        loan = create_onboarding_loan(loan_number="LN-ENT-2", borrower_name="Ig Nored")
        resp = api.create_escrow_account(
            loan["id"], {"target_cushion_cents": 999999, "balance_cents": 777}, EA1)
        account = validate_success(resp, 201)
        assert account["target_cushion_cents"] == 0, (
            "target_cushion_cents is computed; the input value 999999 is ignored")
        assert account["balance_cents"] == 0, (
            "balance_cents is computed; the input value 777 is ignored")
        assert account["account_status"] == "SETUP"
        assert account["hold_status"] == "NONE"
        assert account["loan_id"] == loan["id"]

    def test_second_escrow_account_for_same_loan_rejected(self, api):
        """PRD: "An `EscrowAnalyst` creates the loan's single escrow account; a
        second attempt is rejected with `ERR_ESCROW_ACCOUNT_EXISTS`"

        Design: Corner/validations/escrow_account_exists_rejected
        """
        loan = create_onboarding_loan(loan_number="LN-VAL-2", borrower_name="One Only")
        validate_success(api.create_escrow_account(loan["id"], {}, EA1), 201)

        resp = api.create_escrow_account(loan["id"], {}, EA1)
        validate_error(resp, ApiErrorId.ERR_ESCROW_ACCOUNT_EXISTS)

        accounts, meta = validate_paginated(
            api.list_escrow_accounts(EA1, params={"loan_id": loan["id"]}))
        assert len(accounts) == 1, "one escrow account per loan"

    def test_duplicate_loan_number_rejected(self, api):
        """PRD: "`loan_number` (unique across all loans — a duplicate is
        rejected with `ERR_DUPLICATE_LOAN_NUMBER`)"

        Design: Corner/validations/duplicate_loan_number_rejected
        """
        validate_success(api.create_loan(
            create_loan_payload(loan_number="LN-VAL-3", borrower_name="First Copy"),
            CO1), 201)
        resp = api.create_loan(
            create_loan_payload(loan_number="LN-VAL-3", borrower_name="Second Copy"),
            CO1)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LOAN_NUMBER)

    def test_second_active_line_item_of_same_type_rejected(self, api):
        """PRD: "At most one `ACTIVE` line item per `expense_type` may exist on
        an account; a duplicate is rejected with
        `ERR_DUPLICATE_LINE_ITEM_TYPE`."

        Design: Corner/validations/duplicate_line_item_type_rejected
        """
        ctx = setup_active_account(loan_number="LN-VAL-4")
        second_payee = create_verified_payee(
            legal_name="City Collector", remit_to_address="2 Hall Ave",
            ach_routing_mask="****4321")

        resp = api.create_line_item(
            ctx["account"]["id"],
            create_line_item_payload(
                second_payee["id"], expense_type="PROPERTY_TAX",
                expected_annual_amount_cents=60_000, installments_per_year=1,
                first_due_date="2027-02-01"),
            EA1)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LINE_ITEM_TYPE)


class TestLoanActivationGates:
    def test_activate_loan_without_active_escrow_rejected(self, api):
        """PRD: "Before an `ONBOARDING` loan can be activated, a loan flagged
        `escrow_required` must already have an escrow account in
        `account_status` `ACTIVE`; activation without one is rejected with
        `ERR_ESCROW_NOT_ACTIVE`."

        Design: Corner/validations/loan_activate_without_active_escrow_rejected
        """
        loan = create_onboarding_loan(loan_number="LN-VAL-15",
                                      borrower_name="Not Ready")
        get_success_data(api.create_escrow_account(loan["id"], {}, EA1))

        resp = api.activate_loan(loan["id"], CO1)
        validate_error(resp, ApiErrorId.ERR_ESCROW_NOT_ACTIVE)

        loan_after = validate_success(api.get_loan(loan["id"], CO1), 200)
        assert loan_after["status"] == "ONBOARDING", "loan remains ONBOARDING"


class TestLoanTerminalTransitions:
    def test_payoff_closes_escrow_and_refunds_residual(self, api):
        """PRD: "Both transitions cascade identically: the escrow account moves
        to `CLOSED` (from either `ACTIVE` or `SUSPENDED`), any residual
        `balance_cents` greater than zero is returned to the borrower as a
        `SURPLUS_REFUND` ledger entry of negative the balance so the balance
        becomes exactly 0, every disbursement still `SCHEDULED` or `BLOCKED`
        moves to `CANCELLED`, and the loan's `version` increments."

        Design: Corner/state_machines/loan_payoff_closes_escrow_with_refund
        """
        ctx, disb = setup_account_with_scheduled_disbursement(
            loan_number="LN-SM-6", deposit_amount=50_000)
        acct_id = ctx["account"]["id"]

        loan = validate_success(api.payoff_loan(ctx["loan"]["id"], CO1), 200)
        assert loan["status"] == "PAID_OFF"

        account = get_account(acct_id)
        assert account["account_status"] == "CLOSED"
        assert account["balance_cents"] == 0, (
            "the residual balance is refunded so the balance becomes exactly 0")

        refunds = [e for e in get_ledger(acct_id) if e["entry_type"] == "SURPLUS_REFUND"]
        assert len(refunds) == 1 and refunds[0]["amount_cents"] == -50_000, (
            "SURPLUS_REFUND of negative the residual balance is posted")
        assert_balance_conservation(account, get_ledger(acct_id))

        disb_after = validate_success(api.get_disbursement(disb["id"], EA1), 200)
        assert disb_after["status"] == "CANCELLED"

    def test_payoff_blocked_while_advance_outstanding(self, api):
        """PRD: "Payoff is rejected with `ERR_ADVANCE_OUTSTANDING` while any
        advance on the loan's escrow account is `OUTSTANDING` or `RECOVERING`."

        Design: Corner/validations/payoff_blocked_by_outstanding_advance
        """
        # Balance 50000, disbursement 70000: the release fronts a 20000 advance.
        ctx, disb = setup_released_disbursement(
            loan_number="LN-VAL-14", deposit_amount=50_000,
            disbursement_amount=70_000)
        advances, _ = validate_paginated(
            api.list_advances(ctx["account"]["id"], EA1))
        assert advances and advances[0]["status"] == "OUTSTANDING"

        resp = api.payoff_loan(ctx["loan"]["id"], CO1)
        validate_error(resp, ApiErrorId.ERR_ADVANCE_OUTSTANDING)

        loan_after = validate_success(api.get_loan(ctx["loan"]["id"], CO1), 200)
        assert loan_after["status"] == "ACTIVE", "loan remains ACTIVE"

    def test_transfer_out_blocked_by_open_error_case(self, api):
        """PRD: "Transfer-out is rejected with `ERR_UNRESOLVED_ERROR_CASE` while
        any error case on the loan sits in `RECEIVED`, `ACKNOWLEDGED`,
        `INVESTIGATING`, or `EXTENDED`."

        Design: Corner/validations/transfer_blocked_by_open_error_case
        """
        loan = create_active_bare_loan(loan_number="LN-VAL-13",
                                       borrower_name="Trans Fer")
        file_error_case(loan["id"], error_type="OTHER_COVERED",
                        description="Statement missing")

        resp = api.transfer_out_loan(loan["id"], CO1)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_ERROR_CASE)

        loan_after = validate_success(api.get_loan(loan["id"], CO1), 200)
        assert loan_after["status"] == "ACTIVE", "loan remains ACTIVE"
