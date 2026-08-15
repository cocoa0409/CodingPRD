"""Transaction authorization gating (PRD §3.3) and the reversal cascade
(PRD §3.4): election-dependent pay-or-return outcomes, fee voiding, and
charge-off recovery credits."""
from test_helpers import (
    ApiErrorId,
    api_client,
    authorize,
    fund_account,
    get_account,
    get_batch,
    get_fee,
    get_success_data,
    get_transaction,
    list_fees,
    make_account,
    make_account_holder_headers,
    make_charged_off_scenario,
    make_opted_in_account,
    make_posted_fee_scenario,
    make_program,
    make_restricted_scenario,
    open_batch,
    run_posting_day,
    seal_batch,
    settle_batch,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, CLERK, TELLER


class TestOneTimeDebitOutcomeDependsOnElectionState:
    def _setup(self):
        """Opted-in account overdrawn once (fee posted, ledger -5500), then the
        election is revoked and a 1000 one-time debit is authorized into an
        OPEN 2026-08-04 batch."""
        program = make_program(name="OD-X", daily_fee_cap_cents=100000,
                               max_daily_fees_count=10)
        account, election = make_opted_in_account(program["id"],
                                                  holder_name="Holder X")
        run_posting_day(program["id"], "2026-08-03", account["id"],
                        [("DEBIT_ONE_TIME", 2000)], settle=True)
        holder = make_account_holder_headers(account["id"])
        validate_success(api_client.revoke_opt_in_election(election["id"], holder))
        batch2 = open_batch(program["id"], "2026-08-04")
        txn2 = authorize(account["id"], "DEBIT_ONE_TIME", 1000)
        return program, account, election, batch2, txn2, holder

    def test_revoked_election_returns_debit_without_touching_balance(self, api):
        """PRD §3.4: "If the projection is negative, the item is payable unless
        it is a `DEBIT_ONE_TIME` and the account has no `OPTED_IN` election; a
        non-payable one-time debit is moved to `RETURNED_NSF` with its
        `batch_id`, `posting_sequence`, and `posted_date` assigned, the balance
        left unchanged, and no fee of any kind created."

        Design: Difficulty/cross_entity_state_dependency/onetime_debit_outcome_depends_on_election_state
        """
        _, account, _, batch2, txn2, _ = self._setup()
        seal = seal_batch(batch2["id"])
        assert seal["items_returned_count"] == 1
        assert seal["fees_assessed_count"] == 0
        assert get_transaction(txn2["id"])["status"] == "RETURNED_NSF"

        settle_batch(batch2["id"])
        # The returned item never touched the balance.
        assert get_account(account["id"])["ledger_balance_cents"] == -5500

    def test_reinstated_election_posts_same_debit_with_fee(self, api):
        """PRD §3.4: "Recurring debits, ACH debits, and checks are always
        payable into overdraft regardless of election status, as is any
        one-time debit while the account's election stands `OPTED_IN`."
        PRD §3.2: "Reinstating moves `REVOKED` back to `OPTED_IN`".

        Design: Difficulty/cross_entity_state_dependency/onetime_debit_outcome_depends_on_election_state
        """
        program, account, election, batch2, _, holder = self._setup()
        seal_batch(batch2["id"])
        settle_batch(batch2["id"])
        validate_success(api.reinstate_opt_in_election(
            election["id"], {"disclosure_version": "D1"}, holder))

        batch3 = open_batch(program["id"], "2026-08-05")
        txn3 = authorize(account["id"], "DEBIT_ONE_TIME", 1000)
        seal3 = seal_batch(batch3["id"])
        assert seal3["fees_assessed_count"] == 1
        assert get_transaction(txn3["id"])["status"] == "POSTED"


class TestReversalCascadeVoidsFeeRestoresLedger:
    def _setup(self):
        """Funded account (10000); 2026-08-04 batch with a 12000 one-time
        debit sealed (item POSTED, fee ASSESSED) and left SEALED."""
        program = make_program(name="OD-V")
        account, _ = make_opted_in_account(program["id"], holder_name="Holder V")
        fund_account(program["id"], account["id"], 10000, settle=True)
        batch = open_batch(program["id"], "2026-08-04")
        txn = authorize(account["id"], "DEBIT_ONE_TIME", 12000)
        seal = seal_batch(batch["id"])
        assert seal["fees_assessed_count"] == 1
        fee = list_fees(batch_id=batch["id"])[0]
        return program, account, batch, txn, fee

    def test_reverse_restores_ledger_and_voids_fee(self, api):
        """PRD §3.4: "While a transaction's batch remains `SEALED`, an
        `OperationsClerk` may reverse a `POSTED` transaction, moving it to
        `REVERSED`" and "Reversal credits the account's
        `ledger_balance_cents` back by the `amount_cents` of a debit, or debits
        it back for a credit."
        PRD §3.4: "Any `OverdraftFee` rows whose `transaction_id` names the
        reversed transaction and that are still `ASSESSED` become `VOIDED`".

        Design: Difficulty/transitive_cascade/reversal_cascade_voids_fee_restores_ledger
        """
        _, account, _, txn, fee = self._setup()
        reversed_txn = validate_success(
            api.reverse_transaction(txn["id"], CLERK))
        assert reversed_txn["status"] == "REVERSED"
        assert get_fee(fee["id"])["status"] == "VOIDED"
        # -2000 working balance + 12000 credit-back.
        assert get_account(account["id"])["ledger_balance_cents"] == 10000

    def test_void_counts_toward_lifetime_waived_and_batch_counters_stay(self, api):
        """PRD §3.4: "Any `OverdraftFee` rows whose `transaction_id` names the
        reversed transaction and that are still `ASSESSED` become `VOIDED` — a
        fee that never posted is never debited — and their voided amounts are
        added to the account's `lifetime_fees_waived_cents`."

        Design: Difficulty/transitive_cascade/reversal_cascade_voids_fee_restores_ledger
        """
        _, account, batch, txn, _ = self._setup()
        validate_success(api.reverse_transaction(txn["id"], CLERK))
        account_after = get_account(account["id"])
        assert account_after["lifetime_fees_assessed_cents"] == 3500
        assert account_after["lifetime_fees_waived_cents"] == 3500
        # Batch seal counters are historical and unchanged by the reversal.
        assert get_batch(batch["id"])["fees_assessed_count"] == 1


class TestRestrictedAccountDebitRejectedCreditAllowed:
    def test_restricted_blocks_new_debits_but_accepts_credits(self, api):
        """PRD §3.3: "On a `RESTRICTED` account, new debit authorizations are
        rejected with `ERR_ACCOUNT_RESTRICTED`, though credits remain
        welcome."

        Design: Corner/validations/restricted_account_debit_rejected_credit_allowed
        """
        ctx = make_restricted_scenario()
        account = get_account(ctx["account"]["id"])
        assert account["status"] == "RESTRICTED"

        holder = make_account_holder_headers(account["id"])
        debit = api.create_transaction(
            {"account_id": account["id"], "type": "DEBIT_ONE_TIME",
             "amount_cents": 100}, holder)
        validate_error(debit, ApiErrorId.ERR_ACCOUNT_RESTRICTED)

        credit = api.create_transaction(
            {"account_id": account["id"], "type": "CREDIT_DEPOSIT",
             "amount_cents": 100}, holder)
        assert validate_success(credit, 201)["status"] == "AUTHORIZED"


class TestClosedAccountTransactionRejected:
    def test_closed_voluntary_rejects_debits_and_credits(self, api):
        """PRD §3.3: "On a `CLOSED_VOLUNTARY` account every mutation is
        rejected with `ERR_ACCOUNT_CLOSED`."
        PRD §3.3: "A `CLOSED_CHARGEOFF` account admits exactly one operation:
        a `CREDIT_DEPOSIT`, which serves as a charge-off recovery."

        Design: Corner/validations/closed_account_transaction_rejected
        """
        program = make_program(name="OD-V6")
        account = make_account(program["id"], holder_name="H V6")
        fund_account(program["id"], account["id"], 100, settle=False)
        closed = validate_success(api.close_account(account["id"], TELLER))
        assert closed["status"] == "CLOSED_VOLUNTARY"

        holder = make_account_holder_headers(account["id"])
        for txn_type in ("DEBIT_ONE_TIME", "CREDIT_DEPOSIT"):
            resp = api.create_transaction(
                {"account_id": account["id"], "type": txn_type,
                 "amount_cents": 50}, holder)
            validate_error(resp, ApiErrorId.ERR_ACCOUNT_CLOSED)


class TestReverseAfterSettleRejected:
    def test_reversal_window_closes_at_settle(self, api):
        """PRD §3.4: "once the batch has moved on to `SETTLED` — or was
        `CANCELLED` — the window has closed and the attempt fails with
        `ERR_REVERSAL_WINDOW_CLOSED`."

        Design: Corner/validations/reverse_after_settle_rejected
        """
        ctx = make_posted_fee_scenario()
        # Find the overdraft transaction of the settled batch.
        txns = get_success_data(api.list_transactions(
            ADMIN, params={"account_id": ctx["account"]["id"],
                           "batch_id": ctx["batch_id"]}))
        assert len(txns) == 1
        txn = txns[0]
        assert txn["status"] == "POSTED"

        resp = api.reverse_transaction(txn["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_REVERSAL_WINDOW_CLOSED)
        assert get_transaction(txn["id"])["status"] == "POSTED"


class TestRecoveryExceedsChargeoffRejected:
    def test_recovery_over_charged_off_rejected_exact_amount_allowed(self, api):
        """PRD §3.3: "its amount may not exceed the account's remaining
        `charged_off_cents`, else the attempt is rejected with
        `ERR_RECOVERY_EXCEEDS_CHARGEOFF` (HTTP 422)."

        Design: Corner/validations/recovery_exceeds_chargeoff_rejected
        """
        ctx = make_charged_off_scenario()
        account = ctx["account"]
        assert account["status"] == "CLOSED_CHARGEOFF"
        assert account["charged_off_cents"] == 11500

        holder = make_account_holder_headers(account["id"])
        over = api.create_transaction(
            {"account_id": account["id"], "type": "CREDIT_DEPOSIT",
             "amount_cents": 11501}, holder)
        validate_error(over, ApiErrorId.ERR_RECOVERY_EXCEEDS_CHARGEOFF)

        exact = api.create_transaction(
            {"account_id": account["id"], "type": "CREDIT_DEPOSIT",
             "amount_cents": 11500}, holder)
        assert validate_success(exact, 201)["status"] == "POSTED"
