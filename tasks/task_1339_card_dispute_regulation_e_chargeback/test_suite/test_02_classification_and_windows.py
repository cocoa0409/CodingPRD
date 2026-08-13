"""Classification state rules, investigation window computation, and the
inclusive investigation deadline boundary."""
from test_helpers import (
    CLOCK,
    DEADLINES,
    TEST_USERS,
    ApiErrorId,
    classify_case,
    classify_payload,
    create_card_account_payload,
    create_card_transaction_payload,
    create_dispute_payload,
    create_transaction,
    file_dispute,
    grant_credit,
    make_cardholder_headers,
    make_investigator_headers,
    resolve_payload,
    set_clock,
    setup_account_with_dispute,
    validate_error,
    validate_success,
)


class TestClassificationStateRules:
    def test_classify_from_classified_returns_invalid_state(
        self, api, investigator_headers
    ):
        """PRD §3.3: "Classification is the `DisputeInvestigator`'s first act and
        moves a case from `RECEIVED` to `CLASSIFIED`."

        Design: Corner/state_machines/classify_from_classified_returns_invalid_state
        """
        _account, _txn, case = setup_account_with_dispute(
            balance=50000, amount=5000, claim=5000, claimed_delay=5,
            classify=True, is_fraud=False, verified_delay=5,
        )
        resp = api.classify_dispute(
            case["id"],
            classify_payload(is_fraud_claim=True, verified_report_delay_days=5),
            investigator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_resolve_from_received_returns_invalid_state(
        self, api, investigator_headers
    ):
        """PRD §3.4: "Resolution is the `DisputeInvestigator`'s judgment call,
        submitted with an `outcome`" — and per the lifecycle the resolve
        transitions leave from `CLASSIFIED`, so a case still in `RECEIVED` fails
        the state preconditions.
        PRD §2.8: "sixth, entity state preconditions for the requested transition
        (`ERR_INVALID_STATE`, with the more specific
        `ERR_DUPLICATE_ACTIVE_DISPUTE` and `ERR_ACCOUNT_RESTRICTED` where
        applicable)".

        Design: Corner/state_machines/resolve_from_received_returns_invalid_state
        """
        _account, _txn, case = setup_account_with_dispute(
            balance=50000, amount=5000, claim=5000, claimed_delay=5,
            classify=False,
        )
        resp = api.resolve_dispute(
            case["id"], resolve_payload(outcome="NO_ERROR"), investigator_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestInvestigationWindow:
    def test_window_fraud_branch_is_ninety_days(self, api, bank_admin_headers):
        """PRD §3.3: "The window — recorded as `investigation_window_days` — is
        ninety calendar days when the claim is fraud, when the transaction was a
        `POS_PIN` or `POS_SIGNATURE` purchase, or when the account is new under
        the thirty-day rule; it is forty-five calendar days otherwise."
        PRD §3.3: "The `investigation_deadline_at` falls that many calendar days
        after `received_at`, at 23:59:59Z inclusive."

        Design: Difficulty/combinatorial_formula/investigation_window_by_type_fraud_and_account_age
        """
        _account, _txn, case = setup_account_with_dispute(
            balance=50000, amount=5000, txn_type="POS_PIN",
            error_type="UNAUTHORIZED", claim=5000, claimed_delay=1,
            classify=False,
        )
        data = classify_case(case["id"], is_fraud=True, verified_delay=1)
        assert data["investigation_window_days"] == 90, (
            f"fraud branch must yield 90 days, got {data['investigation_window_days']}"
        )
        assert data["investigation_deadline_at"] == DEADLINES["INVESTIGATION_DEADLINE_90D"], (
            f"deadline must be 90 calendar days after 2026-08-03 at 23:59:59Z, "
            f"got {data['investigation_deadline_at']}"
        )

    def test_window_standard_branch_is_forty_five_days(
        self, api, bank_admin_headers
    ):
        """PRD §3.3: "The window — recorded as `investigation_window_days` — is
        ninety calendar days when the claim is fraud, when the transaction was a
        `POS_PIN` or `POS_SIGNATURE` purchase, or when the account is new under
        the thirty-day rule; it is forty-five calendar days otherwise."
        PRD §3.3: "The `investigation_deadline_at` falls that many calendar days
        after `received_at`, at 23:59:59Z inclusive."

        Design: Difficulty/combinatorial_formula/investigation_window_by_type_fraud_and_account_age
        """
        _account, _txn, case = setup_account_with_dispute(
            balance=50000, amount=5000, txn_type="ECOMMERCE",
            error_type="INCORRECT_AMOUNT", claim=5000, claimed_delay=1,
            classify=False,
        )
        data = classify_case(case["id"], is_fraud=False, verified_delay=1)
        assert data["investigation_window_days"] == 45, (
            f"non-fraud ECOMMERCE on an old account must yield 45 days, "
            f"got {data['investigation_window_days']}"
        )
        assert data["investigation_deadline_at"] == DEADLINES["INVESTIGATION_DEADLINE_45D"], (
            f"deadline must be 45 calendar days after 2026-08-03 at 23:59:59Z, "
            f"got {data['investigation_deadline_at']}"
        )


class TestInvestigationDeadlineBoundary:
    def _two_pending_cases(self, api):
        """Two non-fraud classified cases with credits granted (so only the
        investigation-window gate is under test)."""
        set_clock(CLOCK["ACCOUNT_OPEN"])
        account = validate_success(
            api.create_card_account(
                create_card_account_payload(
                    cardholder_name="Boundary A", initial_balance_cents=50000
                ),
                TEST_USERS["bank_admin_headers"],
            ),
            expected_status=201,
        )
        txns = []
        for _merchant in ("BA1", "BA2"):
            txns.append(create_transaction(
                account["id"], amount=7000, txn_type="ECOMMERCE",
                posted_at=CLOCK["TXN_POSTED"],
            ))
        cases = []
        for txn in txns:
            case = file_dispute(
                txn["id"], account["id"], 7000,
                error_type="INCORRECT_AMOUNT", claimed_delay=5,
            )
            classify_case(case["id"], is_fraud=False, verified_delay=5)
            grant_credit(case["id"])
            cases.append(case)
        return account, cases

    def test_resolve_at_inclusive_deadline_succeeds(self, api):
        """PRD §3.4: "This path is only available while the logical clock is at or
        before `investigation_deadline_at` (inclusive at end of day); a late
        `NO_ERROR` is rejected with `ERR_INVESTIGATION_WINDOW_EXPIRED`."

        Design: Difficulty/boundary_precision_check/investigation_deadline_inclusive_boundary
        """
        _account, cases = self._two_pending_cases(api)
        set_clock(DEADLINES["INVESTIGATION_DEADLINE_45D"])
        resp = api.resolve_dispute(
            cases[0]["id"], resolve_payload(outcome="NO_ERROR"),
            make_investigator_headers("ops-inv-1"),
        )
        data = validate_success(resp)
        assert data["status"] == "REVERSAL_PENDING", (
            f"resolve at exactly the inclusive deadline must succeed, "
            f"got {data['status']}"
        )

    def test_resolve_one_second_past_deadline_fails(self, api):
        """PRD §3.4: "This path is only available while the logical clock is at or
        before `investigation_deadline_at` (inclusive at end of day); a late
        `NO_ERROR` is rejected with `ERR_INVESTIGATION_WINDOW_EXPIRED`."

        Design: Difficulty/boundary_precision_check/investigation_deadline_inclusive_boundary
        """
        _account, cases = self._two_pending_cases(api)
        set_clock("2026-09-18T00:00:00Z")
        resp = api.resolve_dispute(
            cases[1]["id"], resolve_payload(outcome="NO_ERROR"),
            make_investigator_headers("ops-inv-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVESTIGATION_WINDOW_EXPIRED)


class TestProvisionalCreditDeadline:
    def test_provisional_credit_deadline_new_vs_old_account(
        self, api, bank_admin_headers
    ):
        """PRD §3.2: "The `provisional_credit_due_at` is ten business days after
        `received_at`, extended to twenty business days when the account is new
        under the thirty-day rule, landing at 23:59:59Z on that business day,
        inclusive."
        PRD §3.1: "an account is treated as new when the disputed transaction's
        posting time falls within thirty days of the account opening."

        Design: Corner/calculations/provisional_credit_deadline_new_vs_old_account
        """
        # Old account: opened 2026-05-01, txn posted 2026-07-01 (60 days later).
        set_clock("2026-05-01T00:00:00Z")
        old_acct = validate_success(
            api.create_card_account(
                create_card_account_payload(
                    cardholder_name="Old", initial_balance_cents=50000
                ),
                bank_admin_headers,
            ),
            expected_status=201,
        )
        old_txn = validate_success(
            api.create_card_transaction(
                create_card_transaction_payload(
                    old_acct["id"], merchant_name="OLD", amount_cents=5000,
                    posted_at="2026-07-01T10:00:00Z",
                ),
                bank_admin_headers,
            ),
            expected_status=201,
        )
        # New account: opened 2026-07-20, txn posted 2026-07-25 (5 days later).
        set_clock("2026-07-20T00:00:00Z")
        new_acct = validate_success(
            api.create_card_account(
                create_card_account_payload(
                    cardholder_name="New", initial_balance_cents=50000
                ),
                bank_admin_headers,
            ),
            expected_status=201,
        )
        new_txn = validate_success(
            api.create_card_transaction(
                create_card_transaction_payload(
                    new_acct["id"], merchant_name="NEW", amount_cents=5000,
                    posted_at="2026-07-25T10:00:00Z",
                ),
                bank_admin_headers,
            ),
            expected_status=201,
        )
        set_clock(CLOCK["DISPUTE_RECEIVED"])
        old_case = validate_success(
            api.create_dispute(
                create_dispute_payload(old_txn["id"], 5000, claimed_report_delay_days=5),
                make_cardholder_headers(old_acct["id"]),
            ),
            expected_status=201,
        )
        new_case = validate_success(
            api.create_dispute(
                create_dispute_payload(new_txn["id"], 5000, claimed_report_delay_days=5),
                make_cardholder_headers(new_acct["id"]),
            ),
            expected_status=201,
        )
        assert old_case["provisional_credit_due_at"] == DEADLINES["PROVISIONAL_DUE_OLD_ACCOUNT"], (
            f"old account: 10 business days after 2026-08-03 must be "
            f"2026-08-17T23:59:59Z, got {old_case['provisional_credit_due_at']}"
        )
        assert new_case["provisional_credit_due_at"] == DEADLINES["PROVISIONAL_DUE_NEW_ACCOUNT"], (
            f"new account: 20 business days after 2026-08-03 must be "
            f"2026-08-31T23:59:59Z, got {new_case['provisional_credit_due_at']}"
        )

    def test_granted_late_flag_boundary(self, api, bank_admin_headers):
        """PRD §3.4: "The credit records `granted_at` from the logical clock and
        computes `granted_late` — true when the grant happens after the case's
        `provisional_credit_due_at`, a compliance fact retained on the record."

        Design: Corner/calculations/granted_late_flag_boundary
        """
        set_clock(CLOCK["ACCOUNT_OPEN"])
        account = validate_success(
            api.create_card_account(
                create_card_account_payload(
                    cardholder_name="Late", initial_balance_cents=90000
                ),
                bank_admin_headers,
            ),
            expected_status=201,
        )
        cases = []
        for _merchant in ("L1", "L2"):
            txn = create_transaction(account["id"], amount=5000)
            case = file_dispute(
                txn["id"], account["id"], 5000,
                error_type="INCORRECT_AMOUNT", claimed_delay=5,
            )
            classify_case(case["id"], is_fraud=False, verified_delay=5)
            cases.append(case)
        # Grant before the due date (2026-08-17T23:59:59Z).
        set_clock("2026-08-10T09:00:00Z")
        credit_on_time = grant_credit(cases[0]["id"])
        # Grant after the due date.
        set_clock("2026-08-20T09:00:00Z")
        credit_late = grant_credit(cases[1]["id"])
        assert credit_on_time["granted_late"] is False, (
            "grant before provisional_credit_due_at must not be flagged late"
        )
        assert credit_late["granted_late"] is True, (
            "grant after provisional_credit_due_at must be flagged late"
        )
