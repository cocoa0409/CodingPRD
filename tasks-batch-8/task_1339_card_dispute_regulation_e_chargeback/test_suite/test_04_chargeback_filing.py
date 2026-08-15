"""Chargeback filing: reason-code compatibility, network filing deadline,
response-window occupancy, filing fee, and chargeback withdrawal."""
from test_helpers import (
    CLOCK,
    ApiErrorId,
    create_card_account_payload,
    create_card_transaction_payload,
    create_dispute_payload,
    file_chargeback,
    get_case,
    make_cardholder_headers,
    set_clock,
    setup_account_with_dispute,
    setup_filed_chargeback,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, classify_case, create_transaction, file_dispute


class TestReasonCodeCompatibility:
    def _fraud_case_ready(self, api):
        account, txn, case = setup_account_with_dispute(
            balance=50000, amount=15000, txn_type="POS_PIN",
            error_type="UNAUTHORIZED", claim=15000, claimed_delay=1,
            classify=True, is_fraud=True, verified_delay=1,
        )
        set_clock(CLOCK["CHARGEBACK_FILED"])
        return account, txn, case

    def test_non_fraud_code_on_fraud_case_rejected(self, api):
        """PRD §3.5: "fraud claims take `V10_4` or `V10_5` on `VISA` and `M4837`
        or `M4870` on `MASTERCARD`, while non-fraud claims take `V13_1` or
        `V13_3` on `VISA` and `M4853` or `M4855` on `MASTERCARD`; any other
        combination is rejected with `ERR_REASON_CODE_MISMATCH`."

        Design: Corner/validations/reason_code_mismatch_fraud_vs_nonfraud
        """
        _account, _txn, case = self._fraud_case_ready(api)
        resp = api.create_chargeback(
            {"dispute_case_id": case["id"], "reason_code": "V13_1"},
            TEST_USERS["chargeback_analyst_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_REASON_CODE_MISMATCH)

    def test_mastercard_code_on_visa_transaction_rejected(self, api):
        """PRD §3.5: "fraud claims take `V10_4` or `V10_5` on `VISA` and `M4837`
        or `M4870` on `MASTERCARD`, while non-fraud claims take `V13_1` or
        `V13_3` on `VISA` and `M4853` or `M4855` on `MASTERCARD`; any other
        combination is rejected with `ERR_REASON_CODE_MISMATCH`."

        Design: Corner/validations/reason_code_mismatch_fraud_vs_nonfraud
        """
        _account, _txn, case = self._fraud_case_ready(api)
        resp = api.create_chargeback(
            {"dispute_case_id": case["id"], "reason_code": "M4837"},
            TEST_USERS["chargeback_analyst_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_REASON_CODE_MISMATCH)

    def test_matching_fraud_visa_code_succeeds(self, api):
        """PRD §3.5: "fraud claims take `V10_4` or `V10_5` on `VISA` and `M4837`
        or `M4870` on `MASTERCARD`".
        PRD §3.5: "A successfully filed chargeback starts in `FILED`".

        Design: Corner/validations/reason_code_mismatch_fraud_vs_nonfraud
        """
        _account, _txn, case = self._fraud_case_ready(api)
        resp = api.create_chargeback(
            {"dispute_case_id": case["id"], "reason_code": "V10_4"},
            TEST_USERS["chargeback_analyst_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "FILED"


class TestNetworkFilingDeadline:
    def _two_mastercard_cases(self, api):
        """Two MASTERCARD non-fraud classified cases on txns posted 2026-07-01,
        so network_filing_deadline_at is 2026-09-29T23:59:59Z."""
        set_clock(CLOCK["ACCOUNT_OPEN"])
        account = validate_success(
            api.create_card_account(
                create_card_account_payload(
                    cardholder_name="MC", initial_balance_cents=50000
                ),
                TEST_USERS["bank_admin_headers"],
            ),
            expected_status=201,
        )
        cases = []
        for hour in ("10", "11"):
            txn = create_transaction(
                account["id"], amount=6000, txn_type="ECOMMERCE",
                network="MASTERCARD", posted_at=f"2026-07-01T{hour}:00:00Z",
            )
            case = file_dispute(
                txn["id"], account["id"], 6000,
                error_type="SERVICE_NOT_RECEIVED", claimed_delay=60,
                received_clock="2026-09-20T09:00:00Z",
            )
            classify_case(case["id"], is_fraud=False, verified_delay=60)
            cases.append(case)
        return account, cases

    def test_filing_on_deadline_day_succeeds(self, api):
        """PRD §3.5: "filing must occur at or before
        `network_filing_deadline_at`, which is the transaction's `posted_at`
        plus 120 calendar days for `VISA` or 90 calendar days for `MASTERCARD`,
        end-of-day inclusive; a late filing is rejected with
        `ERR_NETWORK_DEADLINE_PASSED`."

        Design: Corner/validations/network_filing_deadline_boundary
        """
        _account, cases = self._two_mastercard_cases(api)
        set_clock("2026-09-29T12:00:00Z")
        resp = api.create_chargeback(
            {"dispute_case_id": cases[0]["id"], "reason_code": "M4853"},
            TEST_USERS["chargeback_analyst_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "FILED", (
            "filing at the deadline day (inclusive end-of-day) must succeed"
        )

    def test_filing_after_deadline_rejected(self, api):
        """PRD §3.5: "filing must occur at or before
        `network_filing_deadline_at`, which is the transaction's `posted_at`
        plus 120 calendar days for `VISA` or 90 calendar days for `MASTERCARD`,
        end-of-day inclusive; a late filing is rejected with
        `ERR_NETWORK_DEADLINE_PASSED`."

        Design: Corner/validations/network_filing_deadline_boundary
        """
        _account, cases = self._two_mastercard_cases(api)
        set_clock("2026-09-30T00:00:00Z")
        resp = api.create_chargeback(
            {"dispute_case_id": cases[1]["id"], "reason_code": "M4853"},
            TEST_USERS["chargeback_analyst_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NETWORK_DEADLINE_PASSED)


class TestChargebackWithdraw:
    def test_chargeback_withdraw_returns_case_to_classified(self, api):
        """PRD §3.6: "Withdrawal closes it as `CANCELLED`, returns the case
        `CHARGEBACK_FILED` → `CLASSIFIED`, and returns the transaction
        `CHARGED_BACK` → `DISPUTED`; the filing fee remains accrued on the
        `CANCELLED` record."

        Design: Corner/endpoints/chargeback_withdraw_returns_case_to_classified
        """
        account, txn, case, chargeback = setup_filed_chargeback(
            balance=50000, amount=9000, claim=9000, claimed_delay=10,
        )
        resp = api.withdraw_chargeback(
            chargeback["id"], TEST_USERS["chargeback_analyst_headers"]
        )
        cb = validate_success(resp)
        assert cb["status"] == "CANCELLED"
        assert cb["fees_total_cents"] == 2500, (
            f"filing fee remains accrued on the CANCELLED record, "
            f"got {cb['fees_total_cents']}"
        )
        assert get_case(case["id"])["status"] == "CLASSIFIED"
        from test_helpers import get_success_data
        txns = get_success_data(api.list_account_transactions(
            account["id"], TEST_USERS["chargeback_analyst_headers"],
        ))
        assert txns[0]["status"] == "DISPUTED"


class TestResponseWindowOccupancy:
    def _cancelled_chargeback_scenario(self, api):
        """Chargeback filed 2026-08-05 and withdrawn 2026-08-10; case back in
        CLASSIFIED. The cancelled chargeback's response window is the half-open
        interval [2026-08-05, 2026-09-04T23:59:59Z]."""
        account, txn, case, chargeback = setup_filed_chargeback(
            balance=50000, amount=15000, claim=15000, claimed_delay=10,
        )
        set_clock(CLOCK["CHARGEBACK_WITHDRAWN"])
        validate_success(api.withdraw_chargeback(
            chargeback["id"], TEST_USERS["chargeback_analyst_headers"],
        ))
        return account, txn, case, chargeback

    def test_refile_inside_response_window_rejected(self, api):
        """PRD §3.5: "each chargeback occupies its transaction for the half-open
        interval from its `filed_at` up to but not including its
        `response_window_end_at`, the thirty-day merchant response window ending
        at 23:59:59Z; if any other chargeback on the same transaction currently
        occupies its window, filing is rejected with `ERR_NETWORK_WINDOW_ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/chargeback_refile_blocked_within_response_window
        """
        _account, _txn, case, _cb = self._cancelled_chargeback_scenario(api)
        set_clock("2026-08-20T09:00:00Z")
        resp = api.create_chargeback(
            {"dispute_case_id": case["id"], "reason_code": "V13_1"},
            TEST_USERS["chargeback_analyst_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NETWORK_WINDOW_ACTIVE)

    def test_refile_after_response_window_succeeds(self, api):
        """PRD §3.5: "each chargeback occupies its transaction for the half-open
        interval from its `filed_at` up to but not including its
        `response_window_end_at`, the thirty-day merchant response window ending
        at 23:59:59Z".
        PRD §3.6: "The case is then eligible for a fresh filing — permitted once
        the cancelled chargeback's response window no longer occupies the
        timeline, and still subject to the network filing deadline."

        Design: Difficulty/resource_temporal_overlap/chargeback_refile_blocked_within_response_window
        """
        _account, _txn, case, _cb = self._cancelled_chargeback_scenario(api)
        # 2026-09-05 is past the window whose inclusive end is 2026-09-04.
        set_clock("2026-09-05T09:00:00Z")
        resp = api.create_chargeback(
            {"dispute_case_id": case["id"], "reason_code": "V13_1"},
            TEST_USERS["chargeback_analyst_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "FILED"
