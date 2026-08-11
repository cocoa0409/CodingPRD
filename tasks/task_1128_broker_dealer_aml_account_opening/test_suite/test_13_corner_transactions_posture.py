"""Corner queue: transaction posting rules, aggregates, posture gating, OCC recalc."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_account,
    create_account,
    create_customer,
    create_rep,
    create_rule,
    escalate_alert,
    get_account,
    get_account_version,
    list_alerts_for_account,
    post_security_txn,
    post_transaction_payload,
    post_wire,
    run_daily_sweep,
    run_scan,
    set_clock,
    setup_open_account,
    submit_and_verify_document,
    validate_error,
    validate_success,
)
from test_helpers.test_users import make_rep_headers


class TestSecurityTransactionAmountComputedClientAmountIgnored:
    def test_buy_amount_computed_client_value_ignored(self, api):
        """PRD §3.5: "Security-type movements (`DEPOSIT_CERT`, `DEPOSIT_DTC`, `BUY`,
        `SELL`) take a `security_id` and require `quantity` and `unit_price`; their
        `amount` is computed as quantity times unit price, rounded half up to two
        decimal places, and any client-sent `amount` is ignored."
        100 @ 40.00 computes 4000.00; the client-sent 9999.00 is ignored.

        Design: Corner/entities/security_transaction_amount_computed_client_amount_ignored
        """
        ctx = setup_open_account()
        resp = api_client.post_transaction(
            ctx["account"]["id"],
            {
                "txn_type": "BUY",
                "security_id": "ACME",
                "quantity": 100,
                "unit_price": 40.00,
                "amount": 9999.00,
            },
            make_rep_headers(ctx["rep"]["id"]),
        )
        txn = validate_success(resp, expected_status=201)
        assert txn["amount"] == pytest.approx(4000.00, abs=0.001), (
            f"amount must be computed from quantity*unit_price, got {txn['amount']}"
        )


class TestTransactionDoubleReverseRejected:
    def test_second_reverse_rejected_and_exposure_not_doubled_back(self, api):
        """PRD §3.5: "An `OperationsAnalyst` reverses a transaction from `POSTED` or
        `FLAGGED` (otherwise `ERR_TRANSACTION_NOT_REVERSIBLE`)".
        PRD §3.5: "Reversal is a compensating action: exposure and wire velocity are
        recomputed excluding the reversed transaction, so that posting followed by
        reversal leaves both aggregates equal to their pre-post values" — the
        compensating action cannot double-apply.

        Design: Corner/state_machines/transaction_double_reverse_rejected
        """
        ctx = setup_open_account()
        account_id = ctx["account"]["id"]
        txn = post_security_txn(
            account_id, None, "SELL", "XYZ", 500, 10.00,
            headers=TEST_USERS["ops_headers"],
        )
        resp = api_client.reverse_transaction(
            txn["id"], {"reason": "error"}, TEST_USERS["ops_headers"]
        )
        validate_success(resp)

        resp = api_client.reverse_transaction(
            txn["id"], {"reason": "again"}, TEST_USERS["ops_headers"]
        )
        error = validate_error(resp, ApiErrorId.ERR_TRANSACTION_NOT_REVERSIBLE)
        assert error["error_id"] == "ERR_TRANSACTION_NOT_REVERSIBLE"
        assert get_account(account_id)["exposure_30d_amount"] == pytest.approx(0.00, abs=0.01)


class TestVelocityWindowExcludesTransactionsOlderThan30Days:
    def test_wire_older_than_trailing_window_drops_out(self, api):
        """PRD §3.5: "The account's `wire_velocity_30d_amount` is the sum of `amount`
        over its `WIRE_OUT` transactions not in `REVERSED` whose dates fall in the
        trailing thirty calendar days, both ends inclusive."
        At clock 2026-06-01 the window is [2026-05-02, 2026-06-01]; the 2026-05-01
        wire of 1000.00 falls outside, so a new 200000.00 wire posts and the velocity
        reads 200000.00, not 201000.00.

        Design: Corner/calculations/velocity_window_excludes_transactions_older_than_30_days
        """
        ctx = setup_open_account()
        account_id = ctx["account"]["id"]
        post_wire(account_id, ctx["rep"], 1000.00)

        set_clock("2026-06-01T00:00:00Z")
        wire = post_wire(account_id, ctx["rep"], 200000.00)
        assert wire["status"] == "POSTED", (
            "the expired-window wire must not count against the LOW 250000 limit"
        )
        account = get_account(account_id)
        assert account["wire_velocity_30d_amount"] == pytest.approx(200000.00, abs=0.01)


class TestExposureTierT2T3Boundaries:
    def test_exactly_100000_is_t2_and_exactly_500000_is_t3(self, api):
        """PRD §3.5: "the `exposure_tier` buckets it: `T1` below 100000, `T2` from
        100000 up to but excluding 500000, and `T3` at 500000 or more — exactly 500000
        is `T3`."
        2500 @ 40.00 = exactly 100000.00 lands T2 (inclusive lower bound); adding
        10000 @ 40.00 = 400000.00 reaches exactly 500000.00, which is T3.

        Design: Corner/calculations/exposure_tier_t2_t3_boundaries
        """
        ctx = setup_open_account()
        account_id = ctx["account"]["id"]
        post_security_txn(
            account_id, None, "DEPOSIT_DTC", "BIG", 2500, 40.00,
            headers=TEST_USERS["ops_headers"],
        )
        account = get_account(account_id)
        assert account["exposure_30d_amount"] == pytest.approx(100000.00, abs=0.01)
        assert account["exposure_tier"] == "T2", (
            f"exactly 100000.00 is T2, got {account['exposure_tier']}"
        )

        post_security_txn(
            account_id, None, "DEPOSIT_DTC", "BIG", 10000, 40.00,
            headers=TEST_USERS["ops_headers"],
        )
        account = get_account(account_id)
        assert account["exposure_30d_amount"] == pytest.approx(500000.00, abs=0.01)
        assert account["exposure_tier"] == "T3", (
            f"exactly 500000.00 is T3, got {account['exposure_tier']}"
        )


class TestAuditorCannotPostTransactions:
    def test_independent_auditor_denied_operational_mutation(self, api):
        """PRD §2.1: "An `IndependentAuditor` plans and runs audit engagements,
        records findings, and verifies or accepts remediation — with no operational
        mutation rights elsewhere."
        PRD §4: `POST /aml/accounts/{accountId}/transactions` is authorized for
        `RegisteredRep, OperationsAnalyst` — an auditor's post is rejected
        `ERR_UNAUTHORIZED_ROLE` even on a healthy OPEN account.

        Design: Corner/rbac/auditor_cannot_post_transactions
        """
        ctx = setup_open_account()
        resp = api_client.post_transaction(
            ctx["account"]["id"],
            post_transaction_payload(txn_type="WIRE_OUT", amount=10.00),
            TEST_USERS["auditor_headers"],
        )
        error = validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert error["error_id"] == "ERR_UNAUTHORIZED_ROLE"
        assert resp.status_code == 403


class TestOccRiskRecalcStaleAfterWirePost:
    def test_stale_expected_version_rejected_fresh_version_recalculates(self, api):
        """PRD §2.6: "**Explicit risk recalculation** on an account likewise requires
        `expected_account_version`. Any account mutation since the client's
        observation — a posted transaction changing exposure, an alert creation, a case
        opening or closing, a posture change — invalidates the basis of the
        recalculation, so a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.3: "An explicit recalculation by an `AMLAnalyst` or `ComplianceOfficer`
        runs the `ONGOING` variant, stamps `risk_variant_used` as `ONGOING`".

        Design: Corner/cross_cutting_layers/occ_risk_recalc_stale_after_wire_post
        """
        ctx = setup_open_account()
        account_id = ctx["account"]["id"]
        observed = get_account_version(account_id)
        post_wire(account_id, ctx["rep"], 100.00)

        resp = api_client.recalculate_risk(
            account_id,
            {"expected_account_version": observed},
            TEST_USERS["officer_headers"],
        )
        error = validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert error["error_id"] == "ERR_STALE_VERSION"
        assert resp.status_code == 412

        current = get_account_version(account_id)
        assert current == observed + 1, "the wire post must bump the account version"
        resp = api_client.recalculate_risk(
            account_id,
            {"expected_account_version": current},
            TEST_USERS["officer_headers"],
        )
        recalculated = validate_success(resp)
        assert recalculated["risk_variant_used"] == "ONGOING"


class TestElevatedPostureAutoflagsNewTransactions:
    def test_elevated_account_flags_new_post_standard_does_not(self, api):
        """PRD §3.5: "New transactions normally land in `POSTED`; against an
        `ELEVATED` account they land directly in `FLAGGED`."
        PRD §3.4: "`SEVERE` blocks all new transaction posting and all certificate
        deposit intake with `ERR_POSTURE_SEVERE_BLOCKS`, while `ELEVATED` automatically
        flags every newly posted transaction."
        Account A is ELEVATED (its document expired and was swept); account B is
        STANDARD; the same BUY payload lands FLAGGED on A and POSTED on B.

        Design: Corner/cross_cutting_layers/elevated_posture_autoflags_new_transactions
        """
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep X8", crd_number="CRD-X08")
        cust_a = create_customer(
            rep, customer_type="INDIVIDUAL", full_name="X8A", tax_id="TIN-X08a",
            country_risk_tier="LOW",
        )
        submit_and_verify_document(
            cust_a["id"], rep, document_number="P-X08a", expiry_date="2026-05-03"
        )
        acct_a = create_account(cust_a["id"], rep, product_set=["CASH"])
        approve_account(acct_a["id"])
        cust_b = create_customer(
            rep, customer_type="INDIVIDUAL", full_name="X8B", tax_id="TIN-X08b",
            country_risk_tier="LOW",
        )
        submit_and_verify_document(
            cust_b["id"], rep, document_number="P-X08b", expiry_date="2030-01-01"
        )
        acct_b = create_account(cust_b["id"], rep, product_set=["CASH"])
        approve_account(acct_b["id"])

        set_clock("2026-05-04T00:00:00Z")
        run_daily_sweep()
        assert get_account(acct_a["id"])["aml_posture"] == "ELEVATED"

        txn_a = post_security_txn(acct_a["id"], rep, "BUY", "ACME", 10, 40.00)
        txn_b = post_security_txn(acct_b["id"], rep, "BUY", "ACME", 10, 40.00)
        assert txn_a["status"] == "FLAGGED", (
            f"ELEVATED posture must auto-flag new transactions, got {txn_a['status']}"
        )
        assert txn_b["status"] == "POSTED"


class TestPostureSevereBlocksTransactionPosting:
    def test_severe_posture_blocks_posting_with_403(self, api):
        """PRD §3.4: "Posture gates money movement: `SEVERE` blocks all new transaction
        posting and all certificate deposit intake with `ERR_POSTURE_SEVERE_BLOCKS`".
        PRD §3.4: "Posture rises to `SEVERE` — directly from either `STANDARD` or
        `ELEVATED` — when a match for the account exists in `CONFIRMED`, or when a case
        of `CRITICAL` priority exists in `OPEN`, `INVESTIGATING`, `SAR_RECOMMENDED`, or
        `REOPENED`."
        A severity-160 alert (16000.00 aggregate over a 10000.00 threshold) escalates
        to a CRITICAL case; the still-OPEN account then refuses a fresh wire with 403.

        Design: Corner/validations/posture_severe_blocks_transaction_posting
        """
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep V10", crd_number="CRD-V10")
        customer = create_customer(
            rep, customer_type="INDIVIDUAL", full_name="V10", tax_id="TIN-V10",
            country_risk_tier="LOW",
        )
        submit_and_verify_document(customer["id"], rep, document_number="P-V10")
        account = create_account(customer["id"], rep, product_set=["CASH"])
        approve_account(account["id"])
        create_rule(rule_code="WIRE_VELOCITY", threshold_amount=10000.00, window_days=30,
                    min_transaction_count=1)
        post_wire(account["id"], rep, 16000.00)
        run_scan()
        alert = list_alerts_for_account(account["id"])[0]
        assert alert["severity"] == 160, (
            f"100 * 1.6 ratio * 1.0 multiplier must be 160, got {alert['severity']}"
        )
        resp = api_client.begin_alert_review(alert["id"], TEST_USERS["analyst_headers"])
        validate_success(resp)
        escalation = escalate_alert(alert["id"])
        assert escalation["case_priority"] == "CRITICAL", (
            f"severity 160 >= 150 must map to CRITICAL, got {escalation['case_priority']}"
        )

        account = get_account(account["id"])
        assert account["lifecycle_status"] == "OPEN"
        assert account["aml_posture"] == "SEVERE", (
            f"an open CRITICAL case must drive posture SEVERE, got {account['aml_posture']}"
        )

        resp = api_client.post_transaction(
            account["id"],
            post_transaction_payload(txn_type="WIRE_OUT", amount=10.00),
            make_rep_headers(rep["id"]),
        )
        error = validate_error(resp, ApiErrorId.ERR_POSTURE_SEVERE_BLOCKS)
        assert error["error_id"] == "ERR_POSTURE_SEVERE_BLOCKS"
        assert resp.status_code == 403
