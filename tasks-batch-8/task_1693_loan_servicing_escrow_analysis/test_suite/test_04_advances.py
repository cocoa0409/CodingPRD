"""Corporate advances: recovery waterfall, decomposition invariant, cap."""
from test_helpers import (
    ADVANCE_CAP_CENTS,
    CO1,
    EA1,
    ApiErrorId,
    assert_advance,
    assert_advance_decomposition,
    create_advance_payload,
    create_manual_advance,
    get_account,
    get_success_data,
    post_deposit,
    recover_advance,
    recover_advance_payload,
    set_clock,
    setup_active_account,
    validate_error,
    validate_success,
)


class TestAdvanceWaterfall:
    def test_deposit_recovers_oldest_advance_first(self, api):
        """PRD: "the incoming amount is allocated to the account's
        `OUTSTANDING` and `RECOVERING` advances oldest-first by `created_at`
        ascending, ties broken by larger `outstanding_cents` first."
        PRD: "Each advance in turn absorbs the smaller of the remaining amount
        and its own outstanding"

        Design: Corner/calculations/advance_waterfall_fifo_by_created_at
        """
        ctx = setup_active_account(loan_number="LN-CAL-4")
        acct_id = ctx["account"]["id"]
        set_clock("2026-08-02T00:00:00Z")
        adv1 = create_manual_advance(acct_id, 30_000)
        set_clock("2026-08-03T00:00:00Z")
        adv2 = create_manual_advance(acct_id, 20_000)

        post_deposit(acct_id, 40_000, "2026-08-04")

        adv1_after = validate_success(api.get_advance(adv1["id"], EA1), 200)
        assert adv1_after["recovered_cents"] == 30_000
        assert adv1_after["status"] == "RECOVERED", (
            "the oldest advance is fully recovered before the newer one is touched")
        assert_advance_decomposition(adv1_after)

        adv2_after = validate_success(api.get_advance(adv2["id"], EA1), 200)
        assert adv2_after["recovered_cents"] == 10_000
        assert adv2_after["outstanding_cents"] == 10_000
        assert adv2_after["status"] == "RECOVERING"
        assert_advance_decomposition(adv2_after)

        account = get_account(acct_id)
        assert account["balance_cents"] == 50_000, (
            "50000 advanced in, +40000 deposit, -40000 recovered: "
            "the deposit's net effect is the amount minus the total recovered")


class TestAdvanceDecomposition:
    def test_partial_recovery_keeps_decomposition(self, api):
        """PRD: "`outstanding_cents` is always `amount_cents` minus
        `recovered_cents` minus `written_off_cents`."
        PRD: "An `EscrowAnalyst` may also recover directly from the account
        balance with a chosen `amount_cents`"

        Design: Difficulty/compensating_invariant/advance_recovery_writeoff_decomposition
        """
        ctx = setup_active_account(loan_number="LN-INV-2")
        acct_id = ctx["account"]["id"]
        adv = create_manual_advance(acct_id, 50_000)

        adv_after = recover_advance(adv["id"], 20_000)
        assert adv_after["status"] == "RECOVERING"
        assert adv_after["recovered_cents"] == 20_000
        assert adv_after["outstanding_cents"] == 30_000
        assert adv_after["written_off_cents"] == 0
        assert_advance_decomposition(adv_after)

        account = get_account(acct_id)
        assert account["balance_cents"] == 30_000, (
            "ADVANCE_ISSUED +50000 then ADVANCE_RECOVERY -20000")

    def test_write_off_zeroes_outstanding_without_moving_money(self, api):
        """PRD: "A `ComplianceOfficer` may write off an `OUTSTANDING` or
        `RECOVERING` advance, moving it to the terminal `WRITTEN_OFF` with
        `written_off_cents` set to the full outstanding and `outstanding_cents`
        zeroed."

        Design: Difficulty/compensating_invariant/advance_recovery_writeoff_decomposition
        """
        ctx = setup_active_account(loan_number="LN-INV-2")
        acct_id = ctx["account"]["id"]
        adv = create_manual_advance(acct_id, 50_000)
        recover_advance(adv["id"], 20_000)

        written = validate_success(api.write_off_advance(adv["id"], CO1), 200)
        assert written["status"] == "WRITTEN_OFF"
        assert written["written_off_cents"] == 30_000
        assert written["outstanding_cents"] == 0
        assert written["recovered_cents"] == 20_000
        assert_advance_decomposition(written)

        account = get_account(acct_id)
        assert account["balance_cents"] == 30_000, (
            "write-off posts no ledger entry, so the balance is untouched")


class TestAdvanceRecoveryValidation:
    def test_recovery_above_outstanding_rejected(self, api):
        """PRD: "the amount may not exceed the advance's outstanding
        (`ERR_RECOVERY_EXCEEDS_OUTSTANDING`, HTTP 422) nor the account balance
        (`ERR_INVALID_AMOUNT`, HTTP 422)"

        Design: Corner/validations/recovery_exceeds_outstanding_rejected
        """
        ctx = setup_active_account(loan_number="LN-VAL-10")
        acct_id = ctx["account"]["id"]
        adv = create_manual_advance(acct_id, 10_000)
        # The 5000 deposit auto-recovers half the advance via the waterfall.
        post_deposit(acct_id, 5_000, "2026-08-05")

        adv_mid = validate_success(api.get_advance(adv["id"], EA1), 200)
        assert adv_mid["outstanding_cents"] == 5_000
        assert adv_mid["status"] == "RECOVERING"

        # 6000 exceeds the 5000 outstanding; the 10000 balance would suffice,
        # so the outstanding rule is the one that fires.
        resp = api.recover_advance(adv["id"], recover_advance_payload(6_000), EA1)
        validate_error(resp, ApiErrorId.ERR_RECOVERY_EXCEEDS_OUTSTANDING)

        adv_after = validate_success(api.get_advance(adv["id"], EA1), 200)
        assert adv_after["outstanding_cents"] == 5_000, "rejected recovery changes nothing"
        assert adv_after["status"] == "RECOVERING"


class TestAdvanceCap:
    def test_advance_at_cap_allowed_one_cent_over_rejected(self, api):
        """PRD: "The advance cap is $10,000.00 (1,000,000 cents): creating an
        advance, automatic or manual, that would push the sum of
        `outstanding_cents` over all non-terminal advances of the account above
        the cap is rejected with `ERR_ADVANCE_CAP_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/advance_cap_exceeded_at_cap_plus_one
        """
        ctx = setup_active_account(loan_number="LN-VAL-11")
        acct_id = ctx["account"]["id"]

        at_cap = create_manual_advance(acct_id, ADVANCE_CAP_CENTS)
        assert_advance(at_cap)
        assert at_cap["amount_cents"] == ADVANCE_CAP_CENTS
        assert at_cap["status"] == "OUTSTANDING", "an advance at exactly the cap is allowed"

        resp = api.create_advance(
            acct_id, create_advance_payload(amount_cents=1), CO1)
        validate_error(resp, ApiErrorId.ERR_ADVANCE_CAP_EXCEEDED)
