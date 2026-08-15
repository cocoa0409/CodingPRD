"""Annual reconciliation: computation windows, variants, and settlement."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_customer_account,
    assert_annual_reconciliation,
    assert_ledger_balances_consistent,
    create_annual_reconciliation_payload,
    drive_to_pto_granted,
    get_account,
    list_ledger_entries,
    post_reading,
    set_clock,
    setup_program_with_grid,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_administrator_headers"]

AUGUST = ("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")
SEPTEMBER = ("2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")
OCTOBER = ("2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z")
RUN_WINDOW_INSTANT = "2027-04-15T00:00:00Z"  # inside [2027-04-01, 2027-05-31)


def _operating_account(name, program_overrides=None, tariff_overrides=None):
    """Program + account with an application in PTO_GRANTED, ready to post
    readings. Returns (sc, ctx)."""
    sc = setup_program_with_grid(
        name,
        program_overrides=program_overrides or {},
        tariff_overrides=tariff_overrides or {})
    ctx = add_customer_account(sc, "1")
    drive_to_pto_granted(sc, ctx, size=10_000, production=15_000_000)
    return sc, ctx


class TestTrueUpSumOfPostedRoundings:
    def test_settled_bank_is_sum_of_per_reading_roundings(self, api):
        """PRD §3.9: "Settlement depends on the program's `true_up_mode`, and
        the rounding order is pinned: the credit bank being settled is the sum
        of per-reading cent-rounded credits from §2.8, and the annual figures
        are derived from that posted balance, never from a whole-year
        recompute of raw watt-hours."
        PRD §3.9: "Under `AVOIDED_COST_PAYOUT`, the reconciliation captures
        `credit_balance_at_compute_cents`; `payout_cents` is the smaller of
        that balance and `nsc_cents`, and `forfeited_cents` is the remainder of
        the balance above the payout."

        Design: Difficulty/combinatorial_formula/cf_true_up_sum_of_posted_roundings
        """
        sc, ctx = _operating_account(
            "MC", tariff_overrides={"export_rate_millicents_per_kwh": 12_345})
        acct = ctx["account"]["id"]
        # Each 100 kWh surplus credits round_half_up(1234.5) = 1,235 cents;
        # three postings bank 3,705 cents. A whole-year recompute from raw Wh
        # (3,703.5) would bank 3,704 — the pinned order disagrees with it.
        for window in (AUGUST, SEPTEMBER, OCTOBER):
            post_reading(acct, *window, 0, 100_000)
        assert get_account(acct)["credit_balance_cents"] == 3_705

        set_clock(RUN_WINDOW_INSTANT)
        rec = validate_success(api.create_annual_reconciliation(
            create_annual_reconciliation_payload(acct,
                                                 reconciliation_year=2026),
            ADMIN), 201)
        assert_annual_reconciliation(rec)
        assert rec["surplus_wh"] == 300_000
        assert rec["credit_balance_at_compute_cents"] == 3_705
        assert rec["nsc_cents"] == 1_350  # 300 kWh at 4,500 mc/kWh
        assert rec["payout_cents"] == 1_350
        assert rec["forfeited_cents"] == 2_355

        rec = validate_success(
            api.finalize_annual_reconciliation(rec["id"], ADMIN))
        assert rec["reconciliation_status"] == "SETTLED"
        assert get_account(acct)["credit_balance_cents"] == 0

        entries = list_ledger_entries(acct)
        settlement = {(e["entry_type"], e["amount_cents"]) for e in entries
                      if e["annual_reconciliation_id"] == rec["id"]}
        assert ("TRUE_UP_PAYOUT", -1_350) in settlement
        assert ("TRUE_UP_FORFEIT", -2_355) in settlement

    def test_half_cent_credit_rounds_half_up_at_posting(self, api):
        """PRD §2.6: "Rounding is pinned to the posting moment: every credit
        ledger entry's `amount_cents` is rounded half-up to whole cents when
        the entry is posted, and account balances are sums of those
        already-rounded posted entries, so no sub-cent remainder ever carries
        forward."

        Design: Difficulty/combinatorial_formula/cf_true_up_sum_of_posted_roundings
        """
        sc, ctx = _operating_account(
            "MC2", tariff_overrides={"export_rate_millicents_per_kwh": 12_345})
        acct = ctx["account"]["id"]
        post_reading(acct, *AUGUST, 0, 100_000)
        entries = list_ledger_entries(acct)
        assert len(entries) == 1
        # 100,000 Wh * 12,345 mc/kWh / 1e6 = 1,234.5 -> 1,235 (half up).
        assert entries[0]["amount_cents"] == 1_235

        set_clock(RUN_WINDOW_INSTANT)
        rec = validate_success(api.create_annual_reconciliation(
            create_annual_reconciliation_payload(acct,
                                                 reconciliation_year=2026),
            ADMIN), 201)
        assert rec["credit_balance_at_compute_cents"] == 1_235
        assert rec["surplus_wh"] == 100_000
        assert rec["nsc_cents"] == 450
        assert rec["payout_cents"] == 450
        assert rec["forfeited_cents"] == 785


class TestPayoutCappedByBalance:
    def test_payout_is_min_of_balance_and_nsc(self, api):
        """PRD §3.9: "Under `AVOIDED_COST_PAYOUT`, the reconciliation captures
        `credit_balance_at_compute_cents`; `payout_cents` is the smaller of
        that balance and `nsc_cents`, and `forfeited_cents` is the remainder of
        the balance above the payout. Finalizing a `COMPUTED` reconciliation
        posts a `TRUE_UP_PAYOUT` entry debiting the payout when positive and a
        `TRUE_UP_FORFEIT` entry debiting the forfeiture when positive, zeroing
        the credit bank, and moves the reconciliation to `SETTLED`."

        Design: Corner/calculations/c_nsc_payout_capped_by_balance
        """
        sc, ctx = _operating_account(
            "NSC", tariff_overrides={"export_rate_millicents_per_kwh": 10_000})
        acct = ctx["account"]["id"]
        post_reading(acct, *AUGUST, 0, 500_000)  # 500 kWh -> 5,000 cents
        assert get_account(acct)["credit_balance_cents"] == 5_000

        set_clock(RUN_WINDOW_INSTANT)
        rec = validate_success(api.create_annual_reconciliation(
            create_annual_reconciliation_payload(acct,
                                                 reconciliation_year=2026),
            ADMIN), 201)
        assert rec["surplus_wh"] == 500_000
        assert rec["nsc_cents"] == 2_250  # 500 kWh at 4,500 mc/kWh
        assert rec["credit_balance_at_compute_cents"] == 5_000
        assert rec["payout_cents"] == 2_250
        assert rec["forfeited_cents"] == 2_750

        rec = validate_success(
            api.finalize_annual_reconciliation(rec["id"], ADMIN))
        assert rec["reconciliation_status"] == "SETTLED"
        assert get_account(acct)["credit_balance_cents"] == 0


class TestBankCapForfeiture:
    def test_bank_rollover_forfeits_only_over_cap_energy(self, api):
        """PRD §3.9: "Under `BANK_ROLLOVER` there is no payout: `payout_cents`
        and `forfeited_cents` are both zero, and `forfeited_wh` is the amount
        by which the account's `banked_wh` exceeds the program's `bank_cap_wh`
        — zero when the cap is null or not exceeded. Finalizing posts a
        `BANK_FORFEIT` entry with the forfeited watt-hours negative in
        `quantity_wh` when positive, so the bank rolls forward at no more than
        the cap."

        Design: Corner/calculations/c_bank_cap_forfeiture_at_true_up
        """
        sc, ctx = _operating_account(
            "BC", program_overrides={"metering_variant": "ENERGY_BANKING",
                                     "true_up_mode": "BANK_ROLLOVER",
                                     "bank_cap_wh": 250_000})
        acct = ctx["account"]["id"]
        post_reading(acct, *AUGUST, 0, 300_000)  # bank 300,000 Wh
        assert get_account(acct)["banked_wh"] == 300_000

        set_clock(RUN_WINDOW_INSTANT)
        rec = validate_success(api.create_annual_reconciliation(
            create_annual_reconciliation_payload(acct,
                                                 reconciliation_year=2026),
            ADMIN), 201)
        assert rec["forfeited_wh"] == 50_000
        assert rec["payout_cents"] == 0
        assert rec["forfeited_cents"] == 0

        rec = validate_success(
            api.finalize_annual_reconciliation(rec["id"], ADMIN))
        assert rec["reconciliation_status"] == "SETTLED"
        account = get_account(acct)
        assert account["banked_wh"] == 250_000, "bank rolls forward at the cap"
        assert account["credit_balance_cents"] == 0

        entries = list_ledger_entries(acct)
        forfeits = [e for e in entries if e["entry_type"] == "BANK_FORFEIT"]
        assert len(forfeits) == 1
        assert forfeits[0]["quantity_wh"] == -50_000
        assert forfeits[0]["annual_reconciliation_id"] == rec["id"]
        assert_ledger_balances_consistent(entries, account)


class TestTrueUpInputSet:
    def test_superseded_readings_excluded_from_surplus(self, api):
        """PRD §3.9: "The computed `surplus_wh` sums, over the account's
        `POSTED` readings whose `period_start` falls inside the window
        (superseded and voided readings excluded), each period's positive part
        of export minus import — periods that net to zero or negative
        contribute nothing."

        Design: Corner/calculations/c_reading_input_set_filtering_superseded_excluded
        """
        sc, ctx = _operating_account("ISF")
        acct = ctx["account"]["id"]
        r1 = post_reading(acct, *AUGUST, 0, 100_000)   # +1,200 cents
        r2 = post_reading(acct, *AUGUST, 0, 50_000)    # supersedes, +600
        assert validate_success(
            api.get_meter_reading(r1["id"], ADMIN))["reading_status"] == (
                "SUPERSEDED")
        assert r2["reading_status"] == "POSTED"

        set_clock(RUN_WINDOW_INSTANT)
        rec = validate_success(api.create_annual_reconciliation(
            create_annual_reconciliation_payload(acct,
                                                 reconciliation_year=2026),
            ADMIN), 201)
        assert rec["surplus_wh"] == 50_000, (
            "the superseded 100,000 Wh reading is excluded from the window sum")
        assert rec["credit_balance_at_compute_cents"] == 600
        assert rec["nsc_cents"] == 225  # 50 kWh at 4,500 mc/kWh
        assert rec["payout_cents"] == 225
        assert rec["forfeited_cents"] == 375


class TestTrueUpRunWindow:
    def test_computation_before_window_end_rejected(self, api):
        """PRD §3.9: "Computation is allowed only during the run window — from
        `window_end` up to but not including sixty days after it — with
        attempts outside rejected as `ERR_TRUE_UP_WINDOW_NOT_OPEN`"

        Design: Corner/validations/v_true_up_window_not_open
        """
        sc, ctx = _operating_account("TW")
        acct = ctx["account"]["id"]
        post_reading(acct, *AUGUST, 0, 100_000)
        # Year-2026 window ends 2027-04-01; the run window is not yet open.
        set_clock("2027-03-15T00:00:00Z")
        resp = api.create_annual_reconciliation(
            create_annual_reconciliation_payload(acct,
                                                 reconciliation_year=2026),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_TRUE_UP_WINDOW_NOT_OPEN, 422)


class TestDuplicateTrueUp:
    def test_one_non_void_reconciliation_per_account_year(self, api):
        """PRD §3.9: "at most one reconciliation in `COMPUTED` or `SETTLED`
        status may exist per account and year, with duplicates rejected as
        `ERR_DUPLICATE_TRUE_UP`."
        PRD §3.9: "A reconciliation computed in error may instead be voided —
        moving it to `VOIDED` with no ledger effect, freeing the account-year
        slot for recomputation."

        Design: Corner/validations/v_duplicate_true_up_rejected
        """
        sc, ctx = _operating_account("DT")
        acct = ctx["account"]["id"]
        post_reading(acct, *AUGUST, 0, 100_000)
        set_clock(RUN_WINDOW_INSTANT)

        rec = validate_success(api.create_annual_reconciliation(
            create_annual_reconciliation_payload(acct,
                                                 reconciliation_year=2026),
            ADMIN), 201)
        assert rec["reconciliation_status"] == "COMPUTED"

        resp = api.create_annual_reconciliation(
            create_annual_reconciliation_payload(acct,
                                                 reconciliation_year=2026),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_TRUE_UP, 422)

        rec = validate_success(
            api.void_annual_reconciliation(rec["id"], ADMIN))
        assert rec["reconciliation_status"] == "VOIDED"

        rec2 = validate_success(api.create_annual_reconciliation(
            create_annual_reconciliation_payload(acct,
                                                 reconciliation_year=2026),
            ADMIN), 201)
        assert rec2["reconciliation_status"] == "COMPUTED"
