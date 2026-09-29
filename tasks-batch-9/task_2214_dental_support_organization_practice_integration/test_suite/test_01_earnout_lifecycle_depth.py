"""Earn-out tranche depth: the two calculation variants, the chained fee-tier
and growth-multiple lookups, the multiple boundary, the conserved pool ledger
and the precedence of tranche state over the pool ceiling."""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_earnout_pool_ledger,
    assert_earnout_tranche,
    build_closed_deal,
    build_reserved_tranche,
    claw_back_tranche,
    make_finance_controller_headers,
    project_tranche,
    read_affiliation,
    read_earnout_tranche,
    reserve_tranche,
    set_clock,
    settle_tranche,
    validate_error,
)

RESERVE_CLOCK = "2027-03-01T00:00:00Z"
SETTLE_CLOCK = "2027-09-02T00:00:00Z"
REPORTED_NET = 210_000_000
REPORTED_EXPENSES = 151_000_000
FINAL_NET = 420_000_000
FINAL_EXPENSES = 285_000_000


@pytest.fixture
def closed_deal():
    """One affiliation carried to CLOSED with its earn-out measurement OPEN."""
    return build_closed_deal()


@pytest.fixture
def reserved_tranche(closed_deal):
    """A PROJECTED tranche reserved provisionally 181 days into its period."""
    return build_reserved_tranche(
        closed_deal,
        reserve_clock=RESERVE_CLOCK,
        reported_net_collections_cents=REPORTED_NET,
        reported_expenses_cents=REPORTED_EXPENSES,
    )


def test_provisional_reservation_annualizes_the_reported_figures(
    closed_deal, reserved_tranche
):
    """PRD §3.9: "Under `PROVISIONAL`, net collections are the reported collections multiplied by 365 days and divided by the elapsed-day count, rounded half up to whole cents, and `lag_holdback_cents` is zero."
    PRD §3.9: "Under `PROVISIONAL` they are the reported expenses multiplied by 365 and divided by the same elapsed-day count, rounded half up, and stored as `annualized_expenses_cents`."

    Design: Difficulty/dual_variant_calc/earnout_provisional_annualization_vs_final_lag_holdback
    """
    assert_earnout_tranche(reserved_tranche)
    assert reserved_tranche["status"] == "RESERVED"
    assert reserved_tranche["variant_applied"] == "PROVISIONAL"
    assert reserved_tranche["annualized_net_collections_cents"] == 423_480_663
    assert reserved_tranche["annualized_expenses_cents"] == 304_502_762
    assert reserved_tranche["lag_holdback_cents"] == 0
    assert reserved_tranche["management_fee_cents"] == 23_291_436
    assert reserved_tranche["adjusted_ebitda_cents"] == 95_686_465
    assert reserved_tranche["growth_bps"] == 632
    assert reserved_tranche["multiple_bps"] == 25_000
    assert reserved_tranche["reserved_cents"] == 14_216_163


def test_final_settlement_holds_back_the_claims_lag_instead_of_annualizing(
    closed_deal, reserved_tranche
):
    """PRD §3.9: "Under `FINAL`, `lag_holdback_cents` is first computed as the reported full-period collections multiplied by the claims-lag holdback of 250 basis points — two and a half percent — divided by ten thousand and rounded half up; net collections are then the full-period collections less that holdback."
    PRD §3.9: "Under `FINAL` the reported expenses are used unscaled with no rounding at all."

    Design: Difficulty/dual_variant_calc/earnout_provisional_annualization_vs_final_lag_holdback
    """
    set_clock(SETTLE_CLOCK)
    settled = settle_tranche(reserved_tranche["id"], FINAL_NET, FINAL_EXPENSES)

    assert settled["status"] == "SETTLED"
    assert settled["variant_applied"] == "FINAL"
    assert settled["lag_holdback_cents"] == 10_500_000
    assert settled["management_fee_cents"] == 22_522_500
    assert settled["adjusted_ebitda_cents"] == 101_977_500
    assert settled["growth_bps"] == 1331
    assert settled["multiple_bps"] == 35_000
    assert settled["awarded_cents"] == 41_921_250
    assert settled["reserved_cents"] == 0


def test_the_two_variants_disagree_on_the_same_tranche_row(
    closed_deal, reserved_tranche
):
    """PRD §3.9: "It is evaluated twice against the same tranche row, in two variants, and both evaluations must respect the conservation identity of §2.8."
    PRD §3.9: "**Step one** produces net collections, and this is the only genuinely variant-divergent arithmetic."

    Design: Difficulty/dual_variant_calc/earnout_provisional_annualization_vs_final_lag_holdback
    """
    provisional_multiple = reserved_tranche["multiple_bps"]
    provisional_growth = reserved_tranche["growth_bps"]

    set_clock(SETTLE_CLOCK)
    settled = settle_tranche(reserved_tranche["id"], FINAL_NET, FINAL_EXPENSES)

    assert settled["id"] == reserved_tranche["id"], "both runs address one row"
    assert settled["growth_bps"] != provisional_growth
    assert settled["multiple_bps"] != provisional_multiple
    assert settled["lag_holdback_cents"] > reserved_tranche["lag_holdback_cents"]
    assert settled["awarded_cents"] != reserved_tranche["reserved_cents"]

    affiliation = read_affiliation(closed_deal["affiliation_id"])
    assert_earnout_pool_ledger(affiliation)


def test_annualized_collections_pick_the_fee_tier_the_multiple_is_built_on(
    closed_deal, reserved_tranche
):
    """PRD §3.9: "Net collections at or above three million dollars take 550 basis points."
    PRD §3.9: "**Step four** computes `management_fee_cents` as net collections multiplied by the selected rate in basis points, divided by ten thousand, rounded half up to whole cents."
    PRD §3.9: "**Step seven** selects `multiple_bps` from the step-six output."

    Design: Difficulty/combinatorial_formula/earnout_chained_fee_tier_then_growth_multiple_lookup
    """
    assert reserved_tranche["annualized_net_collections_cents"] == 423_480_663
    assert reserved_tranche["management_fee_cents"] == 23_291_436
    assert reserved_tranche["adjusted_ebitda_cents"] == 95_686_465
    assert reserved_tranche["growth_bps"] == 632
    assert reserved_tranche["multiple_bps"] == 25_000
    assert reserved_tranche["reserved_cents"] == 14_216_163


def test_partial_period_fee_tier_is_not_the_reported_period_tier(
    closed_deal, reserved_tranche
):
    """PRD §3.9: "Because the provisional variant feeds an *annualized* collections figure into this lookup, a partial period can land in a different fee tier than the same practice's full-year figures, which then shifts adjusted EBITDA, growth and the multiple downstream."

    Design: Difficulty/combinatorial_formula/earnout_chained_fee_tier_then_growth_multiple_lookup
    """
    reported_tier_fee = REPORTED_NET * 600 // 10_000
    assert reported_tier_fee == 12_600_000
    assert reserved_tranche["management_fee_cents"] == 23_291_436
    assert reserved_tranche["management_fee_cents"] != reported_tier_fee, (
        "the fee rate is looked up on the annualized figure, not on the "
        "reported partial-period figure"
    )


def test_growth_at_exactly_fifteen_percent_takes_the_highest_multiple(closed_deal):
    """PRD §3.9: "Growth at or above fifteen percent takes 45,000 basis points, four and a half."
    PRD §3.9: "**Step eight** computes the raw payout as the difference between `adjusted_ebitda_cents` and `baseline_ebitda_cents`, multiplied by `multiple_bps` and divided by ten thousand, rounded half up to whole cents; the payout is then the greater of zero and that raw figure."

    Design: Difficulty/boundary_precision_check/earnout_growth_multiple_tier_boundary_on_settlement
    """
    reserved = build_reserved_tranche(
        closed_deal,
        reserve_clock=RESERVE_CLOCK,
        reported_net_collections_cents=REPORTED_NET,
        reported_expenses_cents=REPORTED_EXPENSES,
    )
    set_clock(SETTLE_CLOCK)
    settled = settle_tranche(reserved["id"], FINAL_NET, 283_477_500)

    assert settled["adjusted_ebitda_cents"] == 103_500_000
    assert settled["growth_bps"] == 1500
    assert settled["multiple_bps"] == 45_000
    assert settled["awarded_cents"] == 60_750_000
    assert settled["status"] == "SETTLED"


def test_growth_one_basis_point_below_the_boundary_takes_the_mid_multiple(closed_deal):
    """PRD §3.9: "Growth at or above eight percent but below 1,500 basis points — fifteen percent — takes 35,000 basis points, three and a half."
    PRD §3.9: "A clawed-back tranche releases its period for reuse."

    Design: Difficulty/boundary_precision_check/earnout_growth_multiple_tier_boundary_on_settlement
    """
    first = build_reserved_tranche(
        closed_deal,
        reserve_clock=RESERVE_CLOCK,
        reported_net_collections_cents=REPORTED_NET,
        reported_expenses_cents=REPORTED_EXPENSES,
    )
    set_clock(SETTLE_CLOCK)
    high = settle_tranche(first["id"], FINAL_NET, 283_477_500)
    claw_back_tranche(first["id"], "restated year-one expense accrual")

    set_clock("2028-03-01T00:00:00Z")
    second = project_tranche(
        closed_deal["affiliation_id"],
        period_label="EO-Y2",
        measurement_start="2027-09-01T00:00:00Z",
        measurement_end="2028-09-01T00:00:00Z",
    )
    reserved = reserve_tranche(
        second["id"],
        100_000_000,
        90_000_000,
        headers=make_finance_controller_headers("u-fin-reserver-2"),
    )
    assert reserved["growth_bps"] == -9109
    assert reserved["multiple_bps"] == 0
    assert reserved["reserved_cents"] == 0

    set_clock("2028-09-02T00:00:00Z")
    settled = settle_tranche(
        second["id"],
        FINAL_NET,
        283_486_500,
        headers=make_finance_controller_headers("u-fin-settler-2"),
    )
    assert settled["adjusted_ebitda_cents"] == 103_491_000
    assert settled["growth_bps"] == 1499
    assert settled["multiple_bps"] == 35_000
    assert settled["awarded_cents"] == 47_218_500
    assert high["awarded_cents"] - settled["awarded_cents"] == 13_531_500

    affiliation = read_affiliation(closed_deal["affiliation_id"])
    assert affiliation["earnout_settled_cents"] == 47_218_500
    assert affiliation["earnout_unallocated_cents"] == 42_781_500
    assert_earnout_pool_ledger(affiliation)


def test_reservation_moves_cents_from_unallocated_into_reserved(
    closed_deal, reserved_tranche
):
    """PRD §2.8: "The invariant that must hold after every single write is that `earnout_pool_cents` equals the sum of `earnout_unallocated_cents`, `earnout_reserved_cents` and `earnout_settled_cents`."
    PRD §3.9: "the affiliation's `earnout_reserved_cents` rises by that amount and its `earnout_unallocated_cents` falls by exactly the same amount"

    Design: Difficulty/compensating_invariant/earnout_pool_conserved_across_reserve_settle_clawback
    """
    affiliation = read_affiliation(closed_deal["affiliation_id"])
    assert affiliation["earnout_pool_cents"] == 90_000_000
    assert affiliation["earnout_reserved_cents"] == 14_216_163
    assert affiliation["earnout_settled_cents"] == 0
    assert affiliation["earnout_unallocated_cents"] == 75_783_837
    assert_earnout_pool_ledger(affiliation)


def test_claw_back_returns_the_pool_to_its_opening_balance_with_zero_drift(
    closed_deal, reserved_tranche
):
    """PRD §3.9: "`clawed_back_cents` is set to the current `awarded_cents`, which is then reset to zero; the affiliation's `earnout_settled_cents` falls by `clawed_back_cents` and its `earnout_unallocated_cents` rises by exactly the same amount, restoring the pool identity with zero drift; the tranche moves `SETTLED → CLAWED_BACK`, which is terminal; and both the tranche's and the affiliation's `version` increment by one."

    Design: Difficulty/compensating_invariant/earnout_pool_conserved_across_reserve_settle_clawback
    """
    set_clock(SETTLE_CLOCK)
    settled = settle_tranche(reserved_tranche["id"], FINAL_NET, FINAL_EXPENSES)
    after_settle = read_affiliation(closed_deal["affiliation_id"])
    assert after_settle["earnout_reserved_cents"] == 0
    assert after_settle["earnout_settled_cents"] == 41_921_250
    assert after_settle["earnout_unallocated_cents"] == 48_078_750
    assert_earnout_pool_ledger(after_settle)

    clawed = claw_back_tranche(
        settled["id"], "year-one collections restated downward"
    )
    assert clawed["status"] == "CLAWED_BACK"
    assert clawed["clawed_back_cents"] == 41_921_250
    assert clawed["awarded_cents"] == 0
    assert clawed["reserved_cents"] == 0

    final = read_affiliation(closed_deal["affiliation_id"])
    assert final["earnout_reserved_cents"] == 0
    assert final["earnout_settled_cents"] == 0
    assert final["earnout_unallocated_cents"] == 90_000_000
    assert_earnout_pool_ledger(final)


def test_settled_tranche_reports_its_state_error_not_the_pool_overage(
    closed_deal, reserved_tranche
):
    """PRD §2.11: "Earn-out tranche status permits the operation — `ERR_INVALID_TRANCHE_STATE` (409). Deliberately far above the pool-capacity check at position 49, so that a tranche that is both wrongly staged and unaffordable reports the state error."
    PRD §3.9: "It requires the tranche to be `RESERVED`, supplies `final_net_collections_cents` and `final_expenses_cents`, and enforces segregation of duties"

    Design: Difficulty/priority_pair_validation_conflict/tranche_state_error_beats_earnout_pool_exceeded
    """
    set_clock(SETTLE_CLOCK)
    settle_tranche(reserved_tranche["id"], FINAL_NET, FINAL_EXPENSES)

    response = api_client.settle_tranche(
        reserved_tranche["id"],
        {
            "final_net_collections_cents": FINAL_NET,
            "final_expenses_cents": 250_000_000,
        },
        make_finance_controller_headers("u-fin-settler"),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_TRANCHE_STATE.value)


def test_rejected_resettlement_writes_no_state_at_all(closed_deal, reserved_tranche):
    """PRD §2.11: "The first check whose condition is violated determines the response, no later check is evaluated, and **no state change whatsoever is written** when any check fires."
    PRD §3.9: "Either overage is refused with `ERR_EARNOUT_POOL_EXCEEDED`, leaving all four pool figures untouched."

    Design: Difficulty/priority_pair_validation_conflict/tranche_state_error_beats_earnout_pool_exceeded
    """
    set_clock(SETTLE_CLOCK)
    settled = settle_tranche(reserved_tranche["id"], FINAL_NET, FINAL_EXPENSES)

    response = api_client.settle_tranche(
        settled["id"],
        {
            "final_net_collections_cents": FINAL_NET,
            "final_expenses_cents": 250_000_000,
        },
        make_finance_controller_headers("u-fin-settler"),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_TRANCHE_STATE.value)

    after = read_earnout_tranche(settled["id"])
    assert after["status"] == "SETTLED"
    assert after["awarded_cents"] == 41_921_250
    assert after["version"] == settled["version"]

    affiliation = read_affiliation(closed_deal["affiliation_id"])
    assert affiliation["earnout_settled_cents"] == 41_921_250
    assert affiliation["earnout_unallocated_cents"] == 48_078_750
    assert_earnout_pool_ledger(affiliation)
