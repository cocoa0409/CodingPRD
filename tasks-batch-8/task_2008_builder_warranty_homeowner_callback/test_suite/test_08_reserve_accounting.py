"""Reserve ledger: accrual schedules and rounding order, true-up re-rating,
manual adjustments with OCC, trend-alert thresholds, and entry immutability."""
from test_helpers import (
    ApiErrorId,
    assert_ledger_conservation,
    assert_reserve_entry,
    get_reserve,
    get_reserve_for_home,
    list_reserve_entries,
    post_reserve_adjustment,
    run_sweep,
    set_clock,
    setup_accrued_reserve,
    setup_home,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

MANAGER = TEST_USERS["manager_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestReserveAccrualProvisionalVsTrueUp:
    def test_provisional_schedule_two_elapsed_months(self, api):
        """PRD §3.7: "At home creation the expected lifetime accrual is set:
        `expected_lifetime_accrual_cents` is the `sale_price_cents` multiplied by
        the accrual rate of one-half of one percent — 0.005 — rounded half-up to
        whole cents."
        PRD §3.7: "Each of the first one hundred nineteen months posts the
        expected accrual divided by 120, each month rounded half-up to whole cents
        individually; the final month posts the remainder — the expected accrual
        minus the sum of the one hundred nineteen rounded postings — so the
        schedule always sums exactly to the expected accrual."

        Design: Difficulty/dual_variant_calc/reserve_accrual_provisional_vs_trueup
        """
        ctx = setup_accrued_reserve()  # closing 2026-06-01, clock 2026-08-01
        reserve = ctx["reserve"]
        assert reserve["expected_lifetime_accrual_cents"] == 200_000
        # Two anniversaries (2026-07-01, 2026-08-01) at 1667 per month.
        assert reserve["accrued_to_date_cents"] == 3_334, (
            f"2 x round_half_up(200000/120) = 2 x 1667, got "
            f"{reserve['accrued_to_date_cents']}"
        )

    def test_true_up_schedule_diverges(self, api):
        """PRD §3.7: "The true-up re-rates the home: the expected lifetime accrual
        is recomputed as the sale price times the revised rate, rounded half-up,
        and a single `TRUE_UP` entry posts for the difference between what the new
        schedule would have accrued for the months already elapsed — the elapsed
        count times the new monthly amount, the new expected divided by 120 and
        rounded half-up — and the `accrued_to_date_cents` standing to date; future
        months then accrue at the new monthly amount."
        PRD §3.7: "Identical homes at identical elapsed months therefore hold
        different accruals once one is re-rated."

        Design: Difficulty/dual_variant_calc/reserve_accrual_provisional_vs_trueup
        """
        ctx = setup_accrued_reserve()
        reserve = ctx["reserve"]
        provisional_accrued = reserve["accrued_to_date_cents"]
        assert provisional_accrued == 3_334

        post_reserve_adjustment(
            reserve["id"],
            {"kind": "TRUE_UP", "revised_accrual_rate": 0.0075,
             "expected_reserve_version": reserve["version"]},
        )
        updated = get_reserve(reserve["id"])
        assert updated["expected_lifetime_accrual_cents"] == 300_000, (
            "round_half_up(40000000 x 0.0075)"
        )
        assert updated["accrued_to_date_cents"] == 5_000, (
            "2 x round_half_up(300000/120) = 2 x 2500 under the re-rated schedule"
        )
        assert updated["accrued_to_date_cents"] != provisional_accrued, (
            "identical home, identical elapsed months, different schedule variant"
        )


class TestReserveAccrualRoundingOrder:
    def _setup_three_months(self, api):
        homeowner, home = setup_home(closing_date="2026-06-01")
        set_clock("2026-09-01T00:00:00Z")  # anniversaries 07-01, 08-01, 09-01
        sweep = run_sweep()
        reserve = get_reserve_for_home(home["id"])
        return home, sweep, reserve

    def test_per_month_rounding_sums_to_5001(self, api):
        """PRD §3.7: "Each of the first one hundred nineteen months posts the
        expected accrual divided by 120, each month rounded half-up to whole cents
        individually; the final month posts the remainder — the expected accrual
        minus the sum of the one hundred nineteen rounded postings — so the
        schedule always sums exactly to the expected accrual."
        PRD §3.7: "This rounding order is pinned: month-by-month, never
        sum-then-round, because the two orders disagree by cents."

        Design: Difficulty/combinatorial_formula/reserve_accrual_rounding_order
        """
        _home, sweep, reserve = self._setup_three_months(api)
        assert sweep["accrual_entries_posted"] == 3
        assert reserve["accrued_to_date_cents"] == 5_001, (
            "3 x 1667 == 5001, NOT 5000 (sum-then-round) — rounding is per-month"
        )
        entries = list_reserve_entries(reserve["id"], kind="ACCRUAL")
        assert len(entries) == 3
        for entry in entries:
            assert entry["amount_cents"] == 1667

    def test_sweep_is_idempotent_per_month(self, api):
        """PRD §3.7: "The sweep posts one `ACCRUAL` entry per fully elapsed,
        not-yet-posted month, numbered from `last_accrual_month_index` plus one
        through the elapsed count, then advances `last_accrual_month_index` to
        match; a month already posted is never posted twice, so re-running the
        sweep is safe."

        Design: Difficulty/combinatorial_formula/reserve_accrual_rounding_order
        """
        _home, sweep, reserve = self._setup_three_months(api)
        assert sweep["accrual_entries_posted"] == 3
        assert reserve["last_accrual_month_index"] == 3

        second = run_sweep()
        assert second["accrual_entries_posted"] == 0, (
            "months already posted are never posted twice"
        )
        after = get_reserve(reserve["id"])
        assert after["accrued_to_date_cents"] == 5_001
        assert after["last_accrual_month_index"] == 3


class TestReserveManualAdjustmentCompensation:
    def _setup_compensated(self, api):
        _homeowner, home = setup_home(closing_date="2026-06-01")
        reserve = get_reserve_for_home(home["id"])
        v1 = reserve["version"]
        post_reserve_adjustment(
            reserve["id"],
            {"kind": "MANUAL_ADJUSTMENT", "amount_cents": 50_000,
             "expected_reserve_version": v1, "note": "Goodwill credit accrual"},
        )
        mid = get_reserve(reserve["id"])
        post_reserve_adjustment(
            reserve["id"],
            {"kind": "MANUAL_ADJUSTMENT", "amount_cents": -50_000,
             "expected_reserve_version": mid["version"],
             "note": "Reverse goodwill accrual - posted in error"},
        )
        final = get_reserve(reserve["id"])
        return reserve, mid, final

    def test_compensating_entries_restore_balance(self, api):
        """PRD §2.8: "The reserve's `balance_cents` is the signed sum of every
        entry ever posted — the ledger's conservation invariant — and its derived
        totals decompose by kind: `accrued_to_date_cents` sums accrual and true-up
        amounts, `drawn_to_date_cents` sums the absolute values of draws, and
        `recovered_to_date_cents` sums recoveries."
        PRD §3.7: "A `MANUAL_ADJUSTMENT` carries a signed, non-zero `amount_cents`;
        a zero adjustment is `ERR_INVALID_ADJUSTMENT`."

        Design: Difficulty/compensating_invariant/reserve_manual_adjustment_compensation
        """
        reserve, mid, final = self._setup_compensated(api)
        assert reserve["balance_cents"] == 0
        assert mid["balance_cents"] == 50_000, "forward action"
        assert final["balance_cents"] == reserve["balance_cents"] == 0, (
            "compensating action restores the conserved balance exactly"
        )
        entries = list_reserve_entries(reserve["id"])
        assert [e["amount_cents"] for e in entries] == [50_000, -50_000]
        assert_ledger_conservation(final, entries)

    def test_each_adjustment_steps_version_by_one(self, api):
        """PRD §2.9: "A successful adjustment itself increments the reserve's
        `version` by one."
        PRD §3.1: "Creating the home also creates its warranty reserve — version
        1, zero balance".

        Design: Difficulty/compensating_invariant/reserve_manual_adjustment_compensation
        """
        reserve, mid, final = self._setup_compensated(api)
        assert reserve["version"] == 1
        assert mid["version"] == reserve["version"] + 1
        assert final["version"] == reserve["version"] + 2, (
            "two successful adjustments step the version 1 -> 2 -> 3"
        )


def test_reserve_alert_threshold_boundary(api):
    """PRD §3.7: "A balance below zero is `DEPLETED`. Otherwise, a balance below
    the alert threshold — one fifth of the expected lifetime accrual, rounded
    half-up to whole cents — is `ELEVATED`. Anything at or above the threshold is
    `NORMAL`."
    PRD §3.7: "Both comparisons are strictly-below triggers: a balance exactly
    equal to the threshold is `NORMAL`, and — because the threshold is positive
    whenever the expected accrual is positive — a balance of exactly zero is
    `ELEVATED`."

    Design: Corner/calculations/reserve_alert_threshold_boundary
    """
    _homeowner, home = setup_home(closing_date="2026-06-01")
    reserve = get_reserve_for_home(home["id"])  # expected 200000 -> threshold 40000

    post_reserve_adjustment(
        reserve["id"],
        {"kind": "MANUAL_ADJUSTMENT", "amount_cents": 40_000,
         "expected_reserve_version": reserve["version"],
         "note": "Seed balance to threshold"},
    )
    at_threshold = get_reserve(reserve["id"])
    assert at_threshold["balance_cents"] == 40_000
    assert at_threshold["alert_status"] == "NORMAL", (
        "balance exactly == round_half_up(200000 x 0.20) is NOT elevated"
    )

    post_reserve_adjustment(
        reserve["id"],
        {"kind": "MANUAL_ADJUSTMENT", "amount_cents": -1,
         "expected_reserve_version": at_threshold["version"],
         "note": "One cent below threshold"},
    )
    below = get_reserve(reserve["id"])
    assert below["balance_cents"] == 39_999
    assert below["alert_status"] == "ELEVATED", "strictly-below trigger"


def test_reserve_entry_has_no_version_field(api):
    """PRD §2.5: "A reserve entry is immutable once appended and carries only `id`
    and `created_at`; `updated_at` and `version` are absent."
    PRD §2.8: "Each entry records its `reserve_id`, its `kind`, its signed
    `amount_cents`, and, where relevant, its provenance: `month_index` for
    accruals, `work_order_ref` for draws, `chargeback_ref` or `claim_ref` for
    recoveries, and a free-text `note` for manual entries."
    PRD §2.8: "Entries are read back in chronological order."

    Design: Corner/entities/reserve_entry_has_no_version_field
    """
    ctx = setup_accrued_reserve()  # two ACCRUAL entries posted at 2026-08-01
    entries = list_reserve_entries(ctx["reserve"]["id"])
    assert len(entries) == 2, "sweep posted months 1 and 2"
    for entry in entries:
        assert_reserve_entry(entry)
    assert entries[0]["kind"] == "ACCRUAL"
    assert entries[0]["month_index"] == 1, "first elapsed month posted first"
    assert entries[1]["month_index"] == 2


def test_occ_stale_version_rejected(api):
    """PRD §2.9: "If the reserve's version has advanced since that observation —
    because the sweep posted accruals, a work-order completion posted a draw, or
    another adjustment landed — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412), and the client must re-read the reserve and resubmit with the
    fresh version."
    PRD §2.9: "A successful adjustment itself increments the reserve's `version`
    by one."

    Design: Corner/cross_cutting_layers/occ_stale_version_rejected
    """
    _homeowner, home = setup_home(closing_date="2026-06-01")
    reserve = get_reserve_for_home(home["id"])
    observed_version = reserve["version"]

    entry = post_reserve_adjustment(
        reserve["id"],
        {"kind": "MANUAL_ADJUSTMENT", "amount_cents": 10_000,
         "expected_reserve_version": observed_version, "note": "First writer"},
    )
    assert entry["kind"] == "MANUAL_ADJUSTMENT"

    resp = api_client.post_reserve_adjustment(
        reserve["id"],
        {"kind": "MANUAL_ADJUSTMENT", "amount_cents": 5_000,
         "expected_reserve_version": observed_version, "note": "Stale replay"},
        FINANCE,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    after = get_reserve(reserve["id"])
    assert after["balance_cents"] == 10_000, "stale write applied nothing"
    assert after["version"] == observed_version + 1
