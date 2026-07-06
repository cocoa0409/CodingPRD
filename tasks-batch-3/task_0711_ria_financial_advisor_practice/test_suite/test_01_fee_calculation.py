"""Fee-run basis selection, tiered marginal fee, proration, rounding order, and
the minimum floor (PRD §3.4, §2.9).

Difficulty queue: dual_variant_calc (fee basis), combinatorial_formula (tiered
proration + round-then-sum). Corner queue: floor binds.
"""
import pytest

from test_helpers import (
    validate_success, get_success_data, api_client as api,
    TEST_USERS, make_billing_headers,
    fixtures as fx, factories as f,
    STANDARD_TIERS, STANDARD_MINIMUM_ANNUAL_FEE_CENTS,
)

BILLING = TEST_USERS["billing_headers"]


# ===========================================================================
# Difficulty: dual_variant_calc / fee_basis_arrears_vs_advance_diverge
# ===========================================================================
def test_fee_basis_arrears_uses_period_end_value(api):
    """PRD §3.4: "Under `ARREARS`, the basis is the household's billable assets
    as of the period end — the current `billable_aum_cents`."

    Design: Difficulty/dual_variant_calc/fee_basis_arrears_vs_advance_diverge
    """
    setup = fx.setup_household_with_active_account(
        market_value_cents=200000000, tiers=STANDARD_TIERS,
        minimum_annual_fee_cents=STANDARD_MINIMUM_ANNUAL_FEE_CENTS,
        billing_method="ARREARS")
    hh = setup["household"]
    acct = setup["account"]
    # Re-value the account to 300,000,000 before the Q2 run.
    get_success_data(api.valuate_account(
        acct["id"], {"market_value_cents": 300000000, "equity_value_cents": 0},
        TEST_USERS["advisor_headers"]))
    v = fx.household_version(hh["id"])
    run = get_success_data(api.create_fee_run(
        f.fee_run_payload(hh["id"], v,
                          period_start="2026-04-01", period_end="2026-06-30"),
        make_billing_headers("billing-1")))
    data = validate_success(api.fee_run_state(run["id"], "CALCULATE", BILLING))
    assert data["basis_aum_cents"] == 300000000, \
        f"ARREARS basis must be period-end value, got {data['basis_aum_cents']}"
    assert data["assessed_fee_cents"] == 623288, \
        f"Expected 623288, got {data['assessed_fee_cents']}"


def test_fee_basis_advance_uses_prior_finalized_snapshot(api):
    """PRD §3.4: "Under `ADVANCE`, the basis is the household's billable assets
    as of the period start, which the system reconstructs as the `basis_aum_cents`
    of the household's most recent `FINALIZED` fee run whose `period_end` equals
    this run's `period_start`"

    Design: Difficulty/dual_variant_calc/fee_basis_arrears_vs_advance_diverge
    """
    setup = fx.setup_household_with_active_account(
        market_value_cents=200000000, tiers=STANDARD_TIERS,
        minimum_annual_fee_cents=STANDARD_MINIMUM_ANNUAL_FEE_CENTS,
        billing_method="ADVANCE")
    hh = setup["household"]
    acct = setup["account"]
    # Q1 run finalized at basis 200,000,000 BEFORE the account is re-valued.
    v0 = fx.household_version(hh["id"])
    q1 = fx.create_finalized_fee_run(hh["id"], v0,
                                     period_start="2026-01-01", period_end="2026-04-01")
    assert q1["basis_aum_cents"] == 200000000
    # Now re-value the account to 300,000,000.
    get_success_data(api.valuate_account(
        acct["id"], {"market_value_cents": 300000000, "equity_value_cents": 0},
        TEST_USERS["advisor_headers"]))
    v1 = fx.household_version(hh["id"])
    q2 = get_success_data(api.create_fee_run(
        f.fee_run_payload(hh["id"], v1,
                          period_start="2026-04-01", period_end="2026-06-30"),
        BILLING))
    data = validate_success(api.fee_run_state(q2["id"], "CALCULATE", BILLING))
    assert data["basis_aum_cents"] == 200000000, \
        f"ADVANCE basis must be the prior finalized snapshot, got {data['basis_aum_cents']}"
    assert data["assessed_fee_cents"] == 436301, \
        f"Expected 436301, got {data['assessed_fee_cents']}"


# ===========================================================================
# Difficulty: combinatorial_formula / tiered_marginal_fee_three_tier_proration
# ===========================================================================
def test_tiered_marginal_fee_spans_two_tiers_with_proration(api):
    """PRD §3.4: "Each tier's slice fee is the slice amount multiplied by that
    tier's `annual_rate_bps`, divided by 10000, rounded half up to whole cents
    for that slice independently; the tier slice fees are then summed to give the
    annual fee."
    PRD §3.4: "the prorated figure is the annual fee multiplied by that day count,
    divided by 365, rounded half up to whole cents. This prorated figure is
    `gross_fee_cents`."

    Design: Difficulty/combinatorial_formula/tiered_marginal_fee_three_tier_proration
    """
    setup = fx.setup_household_with_active_account(
        market_value_cents=200000000, tiers=STANDARD_TIERS,
        minimum_annual_fee_cents=STANDARD_MINIMUM_ANNUAL_FEE_CENTS,
        billing_method="ARREARS")
    hh = setup["household"]
    v = fx.household_version(hh["id"])
    run = get_success_data(api.create_fee_run(
        f.fee_run_payload(hh["id"], v,
                          period_start="2026-01-01", period_end="2026-03-31"),
        BILLING))
    data = validate_success(api.fee_run_state(run["id"], "CALCULATE", BILLING))
    assert data["basis_aum_cents"] == 200000000
    assert data["gross_fee_cents"] == 431507, \
        f"Expected 431507, got {data['gross_fee_cents']}"
    assert data["assessed_fee_cents"] == 431507, \
        f"floor must not bind here, got {data['assessed_fee_cents']}"


def test_tiered_fee_full_year_no_proration_loss(api):
    """PRD §3.4: "For each tier, the slice of the basis that falls within that tier
    is the portion of the basis between the tier's lower edge (the previous tier's
    `upper_bound_cents`, or 0 for the first tier) and the tier's `upper_bound_cents`
    (or the whole remaining basis for the open-ended final tier whose
    `upper_bound_cents` is null)."
    PRD §3.4: "the number of days is the difference between `period_end` and
    `period_start` in days, plus one, and the prorated figure is the annual fee
    multiplied by that day count, divided by 365, rounded half up to whole cents."

    A full calendar year (365 inclusive days) yields the annual fee unprorated:
    tier0 100,000,000@100bps=1,000,000 + tier1 100,000,000@75bps=750,000 = 1,750,000.

    Design: Difficulty/combinatorial_formula/tiered_marginal_fee_three_tier_proration
    """
    setup = fx.setup_household_with_active_account(
        market_value_cents=200000000, tiers=STANDARD_TIERS,
        minimum_annual_fee_cents=STANDARD_MINIMUM_ANNUAL_FEE_CENTS,
        billing_method="ARREARS")
    hh = setup["household"]
    v = fx.household_version(hh["id"])
    # 2026-01-01..2026-12-31 inclusive == 365 days -> proration factor 1.
    run = get_success_data(api.create_fee_run(
        f.fee_run_payload(hh["id"], v,
                          period_start="2026-01-01", period_end="2026-12-31"),
        BILLING))
    data = validate_success(api.fee_run_state(run["id"], "CALCULATE", BILLING))
    assert data["gross_fee_cents"] == 1750000, \
        f"Expected 1750000 (full-year annual fee), got {data['gross_fee_cents']}"


# ===========================================================================
# Difficulty: combinatorial_formula / tiered_fee_per_tier_round_then_sum_order
# ===========================================================================
def test_tiered_fee_rounds_each_slice_before_summing(api):
    """PRD §3.4: "Each tier's slice fee is the slice amount multiplied by that
    tier's `annual_rate_bps`, divided by 10000, rounded half up to whole cents
    for that slice independently; the tier slice fees are then summed to give the
    annual fee. Rounding is per slice, then summed — never sum-then-round."

    basis 66,667 split as 33,333 + 33,334 at 100bps: round(3.3333)=3 each ->
    333 + 333 = 666, vs sum-then-round rhu(666.67)=667.

    Design: Difficulty/combinatorial_formula/tiered_fee_per_tier_round_then_sum_order
    """
    setup = fx.setup_household_with_active_account(
        market_value_cents=66667,
        tiers=[{"upper_bound_cents": 33333, "annual_rate_bps": 100},
               {"upper_bound_cents": None, "annual_rate_bps": 100}],
        minimum_annual_fee_cents=0,
        billing_method="ARREARS")
    hh = setup["household"]
    v = fx.household_version(hh["id"])
    # Full year so proration factor is 1; isolates the per-slice rounding.
    run = get_success_data(api.create_fee_run(
        f.fee_run_payload(hh["id"], v,
                          period_start="2026-01-01", period_end="2026-12-31"),
        BILLING))
    data = validate_success(api.fee_run_state(run["id"], "CALCULATE", BILLING))
    assert data["gross_fee_cents"] == 666, \
        f"per-tier-round-then-sum yields 666, got {data['gross_fee_cents']}"


def test_tiered_fee_single_tier_no_split(api):
    """PRD §3.4: "For each tier, the slice of the basis that falls within that tier
    is the portion of the basis between the tier's lower edge (the previous tier's
    `upper_bound_cents`, or 0 for the first tier) and the tier's `upper_bound_cents`
    (or the whole remaining basis for the open-ended final tier whose
    `upper_bound_cents` is null)."

    A single open-ended tier puts the entire basis in one slice: 66,667@100bps =
    rhu(666.67) = 667.

    Design: Difficulty/combinatorial_formula/tiered_fee_per_tier_round_then_sum_order
    """
    setup = fx.setup_household_with_active_account(
        market_value_cents=66667,
        tiers=[{"upper_bound_cents": None, "annual_rate_bps": 100}],
        minimum_annual_fee_cents=0,
        billing_method="ARREARS")
    hh = setup["household"]
    v = fx.household_version(hh["id"])
    run = get_success_data(api.create_fee_run(
        f.fee_run_payload(hh["id"], v,
                          period_start="2026-01-01", period_end="2026-12-31"),
        BILLING))
    data = validate_success(api.fee_run_state(run["id"], "CALCULATE", BILLING))
    assert data["gross_fee_cents"] == 667, \
        f"single-slice basis rounds once: 667, got {data['gross_fee_cents']}"


# ===========================================================================
# Corner: calculations / fee_minimum_floor_binds_on_small_account
# ===========================================================================
def test_fee_minimum_floor_binds_on_small_account(api):
    """PRD §3.4: "when the prorated marginal fee falls below the prorated minimum,
    the floor binds and `assessed_fee_cents` is the prorated minimum, while
    `gross_fee_cents` still records the pre-floor marginal fee."

    Design: Corner/calculations/fee_minimum_floor_binds_on_small_account
    """
    setup = fx.setup_household_with_active_account(
        market_value_cents=5000000, tiers=STANDARD_TIERS,
        minimum_annual_fee_cents=STANDARD_MINIMUM_ANNUAL_FEE_CENTS,
        billing_method="ARREARS")
    hh = setup["household"]
    v = fx.household_version(hh["id"])
    # Full year: gross = 5,000,000 @ 100bps = 50,000; minimum 100,000 binds.
    run = get_success_data(api.create_fee_run(
        f.fee_run_payload(hh["id"], v,
                          period_start="2026-01-01", period_end="2026-12-31"),
        BILLING))
    data = validate_success(api.fee_run_state(run["id"], "CALCULATE", BILLING))
    assert data["gross_fee_cents"] == 50000, \
        f"Expected gross 50000, got {data['gross_fee_cents']}"
    assert data["assessed_fee_cents"] == 100000, \
        f"floor must bind to 100000, got {data['assessed_fee_cents']}"
