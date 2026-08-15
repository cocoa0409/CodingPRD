"""Dividend declaration lifecycle: dual accrual methods, void, period overlap,
rate band, payment runs, and provisional/final reconciliation."""
from test_helpers import (
    ApiErrorId,
    assert_share_account,
    create_declaration_payload,
    create_member,
    declare_dividend,
    get_account,
    list_account_transactions,
    list_declaration_payments,
    open_account,
    post_transaction,
    set_clock,
    setup_charter,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

FILER = TEST_USERS["membership_officer_headers"]
BOARD = TEST_USERS["board_director_headers"]
OPS = TEST_USERS["operations_officer_headers"]


def _july_declared(api, **overrides):
    """A DECLARED July-2026 declaration at 600 bps ADB, payable 2026-08-10."""
    return declare_dividend(**overrides)


class TestAccrualMethodDivergence:
    """Identical account data under the two pinned methods yields different
    dividends: AVERAGE_DAILY_BALANCE 3896 vs MINIMUM_DAILY_BALANCE 510."""

    def _setup(self, api):
        set_clock("2026-06-15")
        _charter, seg_ids = setup_charter()
        member_id = create_member(segment_id=seg_ids[0], name="Ann Abel")
        acct = open_account(member_id, initial_deposit_cents=1_000_000)
        set_clock("2026-08-01")
        post_transaction(acct["id"], "WITHDRAWAL", 900_000, "2026-07-20")
        post_transaction(acct["id"], "DEPOSIT", 500_000, "2026-07-25")
        return member_id, acct

    def test_dividend_method_adb_amount(self, api):
        """PRD §3.7: "Under `AVERAGE_DAILY_BALANCE` the raw dividend is the sum
        of the window's end-of-day balances, multiplied by the effective rate
        (basis points divided by ten thousand) and divided by 365, the fixed
        day-count year. Under `MINIMUM_DAILY_BALANCE` the raw dividend is the
        window's lowest end-of-day balance, multiplied by the effective rate
        and by the window's day count, divided by 365 — for identical inputs
        it yields a strictly smaller amount whenever the balance ever dips
        below its window maximum."

        Design: Difficulty/dual_variant_calc/dividend_method_adb_vs_minimum_balance_diverge
        """
        _member_id, acct = self._setup(api)

        decl_adb = declare_dividend(method="AVERAGE_DAILY_BALANCE")
        amt_adb = list_declaration_payments(decl_adb["id"])[0][
            "accrued_amount_cents"]
        assert amt_adb == 3896, (
            "23,700,000 day-cents x 600 bps / 365 = 3895.89 -> 3896")

        validate_success(api.void_dividend_declaration(decl_adb["id"], BOARD))
        decl_min = declare_dividend(method="MINIMUM_DAILY_BALANCE")
        amt_min = list_declaration_payments(decl_min["id"])[0][
            "accrued_amount_cents"]
        assert amt_min == 510, (
            "Window minimum 100,000 x 600 bps x 31 / 365 = 509.59 -> 510")
        assert amt_adb != amt_min, (
            "Two valid methods produce different results for identical data")

    def test_dividend_method_void_frees_period_for_redeclaration(self, api):
        """PRD §3.7: "VOIDED declarations no longer block."
        PRD §3.7: "Should the board reconsider, a `BoardDirector` may void a
        DECLARED declaration; voiding from any other state fails with
        `ERR_DECLARATION_INVALID_STATE`. Voiding moves every ACCRUED payment
        row of the declaration to VOIDED and touches no account balance"

        Design: Difficulty/dual_variant_calc/dividend_method_adb_vs_minimum_balance_diverge
        """
        _member_id, acct = self._setup(api)

        decl_adb = declare_dividend(method="AVERAGE_DAILY_BALANCE")
        assert decl_adb["declared_pool_cents"] == 3896

        voided = validate_success(
            api.void_dividend_declaration(decl_adb["id"], BOARD))
        assert voided["status"] == "VOIDED"

        decl_min = validate_success(api.create_dividend_declaration(
            create_declaration_payload(method="MINIMUM_DAILY_BALANCE"),
            BOARD), 201)
        assert decl_min["status"] == "DECLARED", (
            "The voided period is free for re-declaration")
        assert decl_min["declared_pool_cents"] == 510


class TestDeclareVoidConservation:
    def test_declare_then_void_conserves_share_balances(self, api):
        """PRD §3.7: "Voiding moves every ACCRUED payment row of the
        declaration to VOIDED and touches no account balance — accrual is a
        computation, never a movement of money."

        Design: Difficulty/compensating_invariant/declare_then_void_conserves_share_balances
        """
        set_clock("2026-06-15")
        _charter, seg_ids = setup_charter()
        member_id = create_member(segment_id=seg_ids[0], name="Conserve Kay",
                                  date_of_birth="1989-09-09")
        acct = open_account(member_id, initial_deposit_cents=100_000)
        set_clock("2026-08-02")
        bal_before = get_account(acct["id"])["balance_cents"]
        assert bal_before == 100_000

        decl = declare_dividend()
        assert decl["declared_pool_cents"] == 510
        voided = validate_success(api.void_dividend_declaration(decl["id"],
                                                                BOARD))
        assert voided["status"] == "VOIDED"

        rows = list_declaration_payments(decl["id"])
        assert len(rows) == 1
        assert rows[0]["status"] == "VOIDED"

        bal_after = get_account(acct["id"])["balance_cents"]
        assert bal_after == 100_000 == bal_before, (
            "Declaration plus void conserves share balances")

    def test_voided_declaration_frees_period_for_redeclaration(self, api):
        """PRD §3.7: "The new period must not overlap any existing declaration
        in DECLARED or PAID status — intervals are closed, so sharing even a
        single boundary day constitutes overlap — otherwise
        `ERR_DIVIDEND_PERIOD_OVERLAP`; VOIDED declarations no longer block."

        Design: Difficulty/compensating_invariant/declare_then_void_conserves_share_balances
        """
        set_clock("2026-06-15")
        _charter, seg_ids = setup_charter()
        member_id = create_member(segment_id=seg_ids[0], name="Conserve Kay",
                                  date_of_birth="1989-09-09")
        open_account(member_id, initial_deposit_cents=100_000)
        set_clock("2026-08-02")

        decl = declare_dividend()
        validate_success(api.void_dividend_declaration(decl["id"], BOARD))

        redeclared = validate_success(api.create_dividend_declaration(
            create_declaration_payload(method="MINIMUM_DAILY_BALANCE"),
            BOARD), 201)
        assert redeclared["status"] == "DECLARED", (
            "A VOIDED declaration does not block re-declaring the same period")


class TestPeriodOverlap:
    def _setup(self, api):
        set_clock("2026-08-02")
        return _july_declared(api)

    def test_dividend_period_closed_interval_overlap_rejected(self, api):
        """PRD §3.7: "The new period must not overlap any existing declaration
        in DECLARED or PAID status — intervals are closed, so sharing even a
        single boundary day constitutes overlap — otherwise
        `ERR_DIVIDEND_PERIOD_OVERLAP`"

        Design: Difficulty/resource_temporal_overlap/dividend_period_closed_interval_overlap_vs_adjacency
        """
        self._setup(api)
        resp = api.create_dividend_declaration(
            create_declaration_payload(period_start="2026-07-31",
                                       period_end="2026-08-15",
                                       payable_date="2026-08-20"),
            BOARD)
        validate_error(resp, ApiErrorId.ERR_DIVIDEND_PERIOD_OVERLAP)

    def test_dividend_period_adjacency_accepted(self, api):
        """PRD §3.7: "`period_start` and `period_end` — a closed interval in
        which both boundary days count"
        PRD §3.7: "The new period must not overlap any existing declaration in
        DECLARED or PAID status — intervals are closed, so sharing even a
        single boundary day constitutes overlap — otherwise
        `ERR_DIVIDEND_PERIOD_OVERLAP`; VOIDED declarations no longer block."

        Design: Difficulty/resource_temporal_overlap/dividend_period_closed_interval_overlap_vs_adjacency
        """
        first = self._setup(api)
        adjacent = validate_success(api.create_dividend_declaration(
            create_declaration_payload(period_start="2026-08-01",
                                       period_end="2026-08-31",
                                       payable_date="2026-09-05"),
            BOARD), 201)
        assert adjacent["status"] == "DECLARED", (
            "period_start one day after the prior period_end shares no day")

        still = validate_success(api.get_dividend_declaration(first["id"],
                                                              BOARD))
        assert still["status"] == "DECLARED"


class TestRateBandPrecedence:
    def _setup(self, api):
        set_clock("2026-08-02")
        return _july_declared(api)

    def test_declaration_with_empty_eligible_set_is_legal(self, api):
        """PRD §3.7: "The eligible set is every share account that is OPEN at
        computation time with an `opened_date` on or before `period_end`;
        CLOSED accounts are excluded entirely."
        PRD §3.7: "The declaration's `declared_pool_cents` is the sum of those
        per-account rounded amounts — the per-account rounding precedes the
        summation, never follows it."

        Design: Difficulty/priority_pair_validation_conflict/declaration_rate_band_constraint_vs_period_overlap_temporal
        """
        decl = self._setup(api)
        assert decl["status"] == "DECLARED"
        assert decl["declared_pool_cents"] == 0, (
            "With no share accounts the eligible set is empty and the pool "
            "sums to zero")

    def test_rate_band_error_precedes_period_overlap(self, api):
        """PRD §2.6: "Every request passes through an ordered ladder of
        validation tiers. The first tier that fails determines the error
        returned; later tiers are never consulted for a request that has
        already been rejected."
        PRD §3.7: "The rate must sit within the board-authorized band of 10 to
        1500 basis points inclusive, otherwise `ERR_DIVIDEND_RATE_OUT_OF_BAND`."

        Design: Difficulty/priority_pair_validation_conflict/declaration_rate_band_constraint_vs_period_overlap_temporal
        """
        self._setup(api)
        resp = api.create_dividend_declaration(
            create_declaration_payload(period_start="2026-07-15",
                                       period_end="2026-08-15",
                                       rate_bps=9999,
                                       payable_date="2026-08-20"),
            BOARD)
        # The payload also overlaps the existing DECLARED period, but the
        # uniqueness/bands tier is evaluated before the temporal tier.
        validate_error(resp, ApiErrorId.ERR_DIVIDEND_RATE_OUT_OF_BAND)


class TestPaymentRun:
    def test_provisional_final_reconciliation_on_backdated_deposit(self, api):
        """PRD §3.7: "The run recomputes every ACCRUED row from the account's
        full transaction history — including backdated rows posted after the
        declaration — using the pinned method and the member's tier as of the
        payment date."
        PRD §3.7: "`credited_amount_cents` holds the recomputed amount,
        `accrual_delta_cents` holds the credited amount minus the accrued
        amount — non-zero exactly when backdated transactions or tier changes
        intervened — `tier_bonus_bps_applied` reflects the payment-date bonus,
        and a SYSTEM ShareTransaction of kind DIVIDEND_CREDIT with
        `posted_date` set to the `payable_date` credits the account, raising
        its `balance_cents` and incrementing its `version`. The declaration's
        `paid_total_cents` — null until now — is set to the sum of
        `credited_amount_cents` over the CREDITED rows, the operator is
        recorded as `paid_by_user_id`, and the declaration becomes PAID, its
        terminal state."

        Design: Corner/calculations/provisional_final_reconciliation_on_backdated_deposit
        """
        set_clock("2026-06-15")
        _charter, seg_ids = setup_charter()
        member_id = create_member(segment_id=seg_ids[0], name="Delta Deb")
        acct = open_account(member_id, initial_deposit_cents=1_000_000)

        set_clock("2026-07-25")
        post_transaction(acct["id"], "WITHDRAWAL", 900_000, "2026-07-20")
        post_transaction(acct["id"], "DEPOSIT", 500_000, "2026-07-25")

        set_clock("2026-08-01")
        decl = declare_dividend()
        assert decl["declared_pool_cents"] == 3896, (
            "Provisional accrual uses data as of the declaration date")

        set_clock("2026-08-03")
        post_transaction(acct["id"], "DEPOSIT", 100_000, "2026-07-10")

        set_clock("2026-08-10")
        paid = validate_success(api.pay_dividend_declaration(decl["id"], OPS))
        assert paid["status"] == "PAID"
        assert paid["paid_total_cents"] == 4258, (
            "25,900,000 day-cents x 600 bps / 365 = 4257.53 -> 4258")
        assert paid["paid_by_user_id"] == "ops-1"

        rows = list_declaration_payments(decl["id"])
        assert len(rows) == 1
        row = rows[0]
        assert row["status"] == "CREDITED"
        assert row["accrued_amount_cents"] == 3896
        assert row["credited_amount_cents"] == 4258
        assert row["accrual_delta_cents"] == 362, (
            "credited minus accrued; the backdated deposit intervened")
        assert paid["paid_total_cents"] != decl["declared_pool_cents"]

        account = get_account(acct["id"])
        assert_share_account(account)
        assert account["balance_cents"] == 704_258, (
            "700,000 + 4,258 DIVIDEND_CREDIT")

        ledger = list_account_transactions(acct["id"])
        credit = ledger[-1]
        assert credit["kind"] == "DIVIDEND_CREDIT"
        assert credit["origin"] == "SYSTEM"
        assert credit["amount_cents"] == 4258
        assert credit["posted_date"] == "2026-08-10", (
            "The dividend credit posts on the payable_date")

    def test_payment_run_partial_exclusion_of_closed_account(self, api):
        """PRD §3.7: "A row whose account is now CLOSED, or whose recomputed
        average end-of-day balance fails the 500-cent gate, moves to VOIDED.
        Every other row moves to CREDITED"
        PRD §3.7: "The declaration's `paid_total_cents` — null until now — is
        set to the sum of `credited_amount_cents` over the CREDITED rows"

        Design: Corner/cross_cutting_layers/payment_run_partial_exclusion_of_closed_account
        """
        set_clock("2026-06-15")
        _charter, seg_ids = setup_charter()
        m1 = create_member(segment_id=seg_ids[0], name="Partial Pat")
        acct1 = open_account(m1, initial_deposit_cents=100_000)
        m2 = create_member(segment_id=seg_ids[0], name="Partial Quinn",
                           date_of_birth="1990-02-02")
        open_account(m2, initial_deposit_cents=50_000)
        acct3 = open_account(m2, account_type="SUPPLEMENTAL",
                             initial_deposit_cents=60_000)

        set_clock("2026-08-02")
        decl = declare_dividend()
        assert decl["declared_pool_cents"] == 1071, "510 + 255 + 306"

        set_clock("2026-08-05")
        validate_success(api.close_share_account(acct3["id"], FILER))

        set_clock("2026-08-10")
        paid = validate_success(api.pay_dividend_declaration(decl["id"], OPS))
        assert paid["status"] == "PAID"
        assert paid["paid_total_cents"] == 765, (
            "510 + 255; the VOIDED row contributes nothing")

        rows = list_declaration_payments(decl["id"])
        assert len(rows) == 3
        assert rows[0]["share_account_id"] == acct1["id"]
        assert rows[0]["status"] == "CREDITED"
        assert rows[0]["credited_amount_cents"] == 510
        assert rows[1]["status"] == "CREDITED"
        assert rows[1]["credited_amount_cents"] == 255
        assert rows[2]["share_account_id"] == acct3["id"]
        assert rows[2]["status"] == "VOIDED", (
            "The account closed between declaration and payment")
        assert rows[2]["accrued_amount_cents"] == 306, (
            "The accrual recorded at declaration is preserved")

        account = get_account(acct1["id"])
        assert account["balance_cents"] == 100_510, (
            "DIVIDEND_CREDIT posted on the payable_date")

    def test_dividend_not_yet_payable_then_payable_on_date(self, api):
        """PRD §3.7: "An `OperationsOfficer` runs payment once the current
        clock date has reached the `payable_date`; an earlier attempt fails
        with `ERR_DIVIDEND_NOT_YET_PAYABLE`, and a declaration no longer
        DECLARED fails with `ERR_DECLARATION_INVALID_STATE`."

        Design: Corner/validations/dividend_not_yet_payable_then_payable_on_date
        """
        set_clock("2026-08-02")
        decl = _july_declared(api)

        set_clock("2026-08-09")
        early = api.pay_dividend_declaration(decl["id"], OPS)
        validate_error(early, ApiErrorId.ERR_DIVIDEND_NOT_YET_PAYABLE)

        set_clock("2026-08-10")
        paid = validate_success(api.pay_dividend_declaration(decl["id"], OPS))
        assert paid["status"] == "PAID", "Payment on the payable_date itself"
        assert paid["paid_total_cents"] == 0, "No eligible accounts"

    def test_payable_date_must_exceed_period_end(self, api):
        """PRD §3.7: "The `payable_date` must fall strictly after `period_end`,
        otherwise `ERR_DATE_ORDER_INVALID`."

        Design: Corner/validations/payable_date_must_exceed_period_end
        """
        resp = api.create_dividend_declaration(
            create_declaration_payload(payable_date="2026-07-31"), BOARD)
        validate_error(resp, ApiErrorId.ERR_DATE_ORDER_INVALID)

    def test_declaration_void_after_paid_rejected(self, api):
        """PRD §3.7: "Should the board reconsider, a `BoardDirector` may void a
        DECLARED declaration; voiding from any other state fails with
        `ERR_DECLARATION_INVALID_STATE`. Voiding moves every ACCRUED payment
        row of the declaration to VOIDED and touches no account balance —
        accrual is a computation, never a movement of money. VOIDED is terminal
        for the declaration."
        PRD §3.7: "the declaration becomes PAID, its terminal state."

        Design: Corner/state_machines/declaration_void_after_paid_rejected
        """
        set_clock("2026-08-02")
        decl = _july_declared(api)
        set_clock("2026-08-10")
        paid = validate_success(api.pay_dividend_declaration(decl["id"], OPS))
        assert paid["status"] == "PAID"
        assert paid["paid_total_cents"] == 0

        resp = api.void_dividend_declaration(decl["id"], BOARD)
        validate_error(resp, ApiErrorId.ERR_DECLARATION_INVALID_STATE)
