"""Household aggregation, breakpoint tiers, account drift, and goal funding —
the derived-figure reconciliations (PRD §2.8, §3.3, §3.6).

Difficulty queue: combinatorial_formula (breakpoint circular dependency),
boundary_precision_check (drift @ tolerance, goal @ 100%), dual_variant_calc
(goal projected vs actual). Corner queue: held-away filtering, drift-zero,
strict boundary, projected variant, valuation drift read, derived reconciliation,
immediate consistency.
"""
import pytest

from test_helpers import (
    validate_success, get_success_data, api_client as api,
    TEST_USERS, fixtures as fx, factories as f,
    STANDARD_TIERS,
)

ADVISOR = TEST_USERS["advisor_headers"]


# ===========================================================================
# Difficulty: combinatorial_formula / householding_breakpoint_circular_dependency_order
# ===========================================================================
def test_breakpoint_tier_at_exact_upper_bound_advances(api):
    """PRD §2.8: "The boundary is strict: an `aggregated_aum_cents` exactly equal
    to a tier's `upper_bound_cents` does not belong to that tier — it falls into
    the next, higher tier."

    Two ACTIVE accounts summing to exactly 100,000,000 (the tier-0 bound) land in
    tier index 1.

    Design: Difficulty/combinatorial_formula/householding_breakpoint_circular_dependency_order
    """
    sched = fx.create_fee_schedule(tiers=STANDARD_TIERS, minimum_annual_fee_cents=0)
    hh = fx.create_household(sched["id"])
    client = fx.create_kyc_verified_client(hh["id"])
    fx.create_active_billable_account(hh["id"], client["id"],
                                      market_value_cents=40000000, account_type="TAXABLE")
    fx.create_active_billable_account(hh["id"], client["id"],
                                      market_value_cents=60000000, account_type="IRA")
    data = validate_success(api.get_household(hh["id"], ADVISOR))
    assert data["aggregated_aum_cents"] == 100000000, \
        f"Expected 100000000, got {data['aggregated_aum_cents']}"
    assert data["breakpoint_tier_index"] == 1, \
        f"exact bound advances to tier 1, got {data['breakpoint_tier_index']}"


def test_breakpoint_tier_one_cent_below_bound_stays(api):
    """PRD §2.8: "Landing one cent below a bound keeps the lower tier; landing
    exactly on the bound advances to the next."

    Design: Difficulty/combinatorial_formula/householding_breakpoint_circular_dependency_order
    """
    sched = fx.create_fee_schedule(tiers=STANDARD_TIERS, minimum_annual_fee_cents=0)
    hh = fx.create_household(sched["id"])
    client = fx.create_kyc_verified_client(hh["id"])
    fx.create_active_billable_account(hh["id"], client["id"],
                                      market_value_cents=99999999)
    data = validate_success(api.get_household(hh["id"], ADVISOR))
    assert data["aggregated_aum_cents"] == 99999999
    assert data["breakpoint_tier_index"] == 0, \
        f"one cent below bound stays in tier 0, got {data['breakpoint_tier_index']}"


# ===========================================================================
# Corner: calculations / breakpoint_tier_below_boundary_strict
# ===========================================================================
def test_breakpoint_tier_below_boundary_strict(api):
    """PRD §2.8: "The selected index is that of the first tier whose
    `upper_bound_cents` is null or strictly greater than `aggregated_aum_cents`."

    Design: Corner/calculations/breakpoint_tier_below_boundary_strict
    """
    sched = fx.create_fee_schedule(tiers=STANDARD_TIERS, minimum_annual_fee_cents=0)
    hh = fx.create_household(sched["id"])
    client = fx.create_kyc_verified_client(hh["id"])
    fx.create_active_billable_account(hh["id"], client["id"],
                                      market_value_cents=99999999)
    data = validate_success(api.get_household(hh["id"], ADVISOR))
    assert data["breakpoint_tier_index"] == 0, \
        f"99,999,999 < 100,000,000 stays in tier 0, got {data['breakpoint_tier_index']}"


# ===========================================================================
# Corner: calculations / held_away_account_excluded_from_billable_aum
# ===========================================================================
def test_held_away_excluded_from_billable_included_in_aggregated(api):
    """PRD §2.8: "The `billable_aum_cents` is the sum of `market_value_cents` over
    the household's member accounts that are simultaneously `ACTIVE`, billable, and
    not held away. The `aggregated_aum_cents` is the broader figure: the sum of
    `market_value_cents` over all the household's `ACTIVE` member accounts,
    including held-away and non-billable ones."

    Design: Corner/calculations/held_away_account_excluded_from_billable_aum
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    client = fx.create_kyc_verified_client(hh["id"])
    fx.create_active_billable_account(hh["id"], client["id"],
                                      market_value_cents=100000000,
                                      billable=True, held_away=False)
    fx.create_active_billable_account(hh["id"], client["id"],
                                      market_value_cents=50000000,
                                      account_type="HELD_AWAY_401K",
                                      custodian="Fidelity",
                                      billable=False, held_away=True)
    data = validate_success(api.get_household(hh["id"], ADVISOR))
    assert data["billable_aum_cents"] == 100000000, \
        f"held-away excluded from billable, got {data['billable_aum_cents']}"
    assert data["aggregated_aum_cents"] == 150000000, \
        f"held-away included in aggregated, got {data['aggregated_aum_cents']}"


# ===========================================================================
# Difficulty: boundary_precision_check / drift_flag_at_exact_tolerance_ge
# ===========================================================================
def test_drift_flag_at_exact_tolerance_flags(api):
    """PRD §3.3: "`rebalance_flagged` is true exactly when `drift_bps` is greater
    than or equal to the policy's `drift_tolerance_bps` — at-tolerance flags."

    Account at 65% actual vs 60% model == 500 bps drift, tolerance 500 -> flagged.

    Design: Difficulty/boundary_precision_check/drift_flag_at_exact_tolerance_ge
    """
    setup = fx.setup_account_with_approved_ips(
        market_value_cents=1000000, equity_value_cents=600000,
        model_equity_pct=60, max_equity_pct=80, drift_tolerance_bps=500)
    acct = setup["account"]
    data = validate_success(api.valuate_account(
        acct["id"], {"market_value_cents": 1000000, "equity_value_cents": 650000},
        ADVISOR))
    assert data["drift_bps"] == 500, f"Expected 500, got {data['drift_bps']}"
    assert data["rebalance_flagged"] is True, \
        "at exactly tolerance the account must be flagged"


def test_drift_one_bp_below_tolerance_not_flagged(api):
    """PRD §3.3: "`rebalance_flagged` is true exactly when `drift_bps` is greater
    than or equal to the policy's `drift_tolerance_bps` — at-tolerance flags."

    49.9% -> rhu(4990) actual ... use 64.99% equity for 499 bps drift (< 500).

    Design: Difficulty/boundary_precision_check/drift_flag_at_exact_tolerance_ge
    """
    setup = fx.setup_account_with_approved_ips(
        market_value_cents=1000000, equity_value_cents=600000,
        model_equity_pct=60, max_equity_pct=80, drift_tolerance_bps=500)
    acct = setup["account"]
    # 649,900 / 1,000,000 = 6499 bps actual vs 6000 model -> 499 bps drift.
    data = validate_success(api.valuate_account(
        acct["id"], {"market_value_cents": 1000000, "equity_value_cents": 649900},
        ADVISOR))
    assert data["drift_bps"] == 499, f"Expected 499, got {data['drift_bps']}"
    assert data["rebalance_flagged"] is False, \
        "499 bps is below the 500 tolerance, must not be flagged"


# ===========================================================================
# Corner: calculations / drift_zero_when_no_approved_ips
# ===========================================================================
def test_drift_zero_when_no_approved_ips(api):
    """PRD §3.3: "If the account's client has no `APPROVED` policy statement,
    there is no model to compare against, so `drift_bps` is 0 and
    `rebalance_flagged` is false."

    Design: Corner/calculations/drift_zero_when_no_approved_ips
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    client = fx.create_kyc_verified_client(hh["id"])  # KYC only, no APPROVED IPS
    # A client with no APPROVED IPS can never reach IPS_SIGNED (PRD §3.1), so an
    # account it owns can never be activated (PRD §3.3). Drift is recomputed on
    # every valuation regardless of account status, so we valuate the PENDING
    # account directly to exercise the no-model -> drift 0 rule faithfully.
    acct = fx.create_account(hh["id"], client["id"],
                             market_value_cents=1000000,
                             equity_value_cents=900000)
    data = validate_success(api.valuate_account(
        acct["id"], {"market_value_cents": 1000000, "equity_value_cents": 900000},
        ADVISOR))
    assert data["drift_bps"] == 0, f"no model -> drift 0, got {data['drift_bps']}"
    assert data["rebalance_flagged"] is False


# ===========================================================================
# Corner: endpoints / account_valuation_recomputes_drift_computed_read
# ===========================================================================
def test_valuation_recomputes_drift_in_response(api):
    """PRD §3.3: "The drift is the absolute value of the difference between those
    two basis-point figures" 70% actual vs 60% model == 1000 bps.

    Design: Corner/endpoints/account_valuation_recomputes_drift_computed_read
    """
    setup = fx.setup_account_with_approved_ips(
        market_value_cents=1000000, equity_value_cents=600000,
        model_equity_pct=60, max_equity_pct=80, drift_tolerance_bps=500)
    acct = setup["account"]
    data = validate_success(api.valuate_account(
        acct["id"], {"market_value_cents": 1000000, "equity_value_cents": 700000},
        ADVISOR))
    assert data["drift_bps"] == 1000, \
        f"70% vs 60% model == 1000 bps, got {data['drift_bps']}"


# ===========================================================================
# Corner: cross_cutting / derived_field_reconciliation_aum_on_valuation
# ===========================================================================
def test_billable_aum_rederived_on_valuation(api):
    """PRD §3.3: "First it recomputes the account's drift, and second it recomputes
    the owning household's `billable_aum_cents`, `aggregated_aum_cents`, and
    `breakpoint_tier_index`."

    Design: Corner/cross_cutting/derived_field_reconciliation_aum_on_valuation
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    client = fx.create_kyc_verified_client(hh["id"])
    acct = fx.create_active_billable_account(hh["id"], client["id"],
                                             market_value_cents=100000000)
    get_success_data(api.valuate_account(
        acct["id"], {"market_value_cents": 250000000, "equity_value_cents": 0},
        ADVISOR))
    data = validate_success(api.get_household(hh["id"], ADVISOR))
    assert data["billable_aum_cents"] == 250000000, \
        f"billable re-derived from new valuation, got {data['billable_aum_cents']}"


# ===========================================================================
# Corner: consistency_model / immediate_consistency_aum_visible_same_response
# ===========================================================================
def test_aum_visible_immediately_after_activate(api):
    """PRD §2.8: "All three start at 0 on a freshly created household and are
    recomputed whenever an account's state changes, whenever an account is
    revalued, or whenever an account is added"

    Design: Corner/consistency_model/immediate_consistency_aum_visible_same_response
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    client = fx.create_kyc_verified_client(hh["id"])
    acct = fx.create_account(hh["id"], client["id"], market_value_cents=80000000)
    # PRD §3.3: account activation requires the owning client be IPS_SIGNED/ACTIVE.
    fx.ensure_ips_signed(client["id"])
    get_success_data(api.account_state(acct["id"], "ACTIVATE", ADVISOR))
    data = validate_success(api.get_household(hh["id"], ADVISOR))
    assert data["billable_aum_cents"] == 80000000, \
        f"AUM visible immediately, got {data['billable_aum_cents']}"


# ===========================================================================
# Difficulty: dual_variant_calc / goal_funding_projected_vs_actual_diverge
# ===========================================================================
def test_goal_funding_actual_variant_while_plan_draft(api):
    """PRD §3.6: "When the plan is `DRAFT` (or otherwise not `ACTIVE`), the actual
    variant applies and the projected value is simply the goal's
    `current_amount_cents` with no projection."

    current 0, target 1,200,000 -> funded_ratio_bps 0 (DRAFT/ACTUAL).

    Design: Difficulty/dual_variant_calc/goal_funding_projected_vs_actual_diverge
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    plan = fx.create_draft_plan(assumed_annual_return_bps=0,
                                monthly_contribution_cents=100000)
    goal = fx.create_goal(plan["id"], target_amount_cents=1200000,
                          target_date="2027-03-01", current_amount_cents=0,
                          priority="ESSENTIAL")
    data = validate_success(api.get_goal(goal["id"], ADVISOR))
    assert data["funded_ratio_bps"] == 0, \
        f"ACTUAL variant on a DRAFT plan: 0, got {data['funded_ratio_bps']}"
    assert data["on_track"] is False


def test_goal_funding_projected_variant_after_activate(api):
    """PRD §3.6: "When the plan is `ACTIVE`, the projected variant applies: the
    goal's current balance is future-valued to the target date, and the assumed
    monthly contributions are future-valued as an annuity, both at the plan's
    assumed monthly return."

    0 return, 100,000/mo, 12 months -> 1,200,000 projected == target 1,200,000
    -> funded_ratio_bps 10000, on_track true.

    Design: Difficulty/dual_variant_calc/goal_funding_projected_vs_actual_diverge
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    plan = fx.create_draft_plan(assumed_annual_return_bps=0,
                                monthly_contribution_cents=100000)
    goal = fx.create_goal(plan["id"], target_amount_cents=1200000,
                          target_date="2027-03-01", current_amount_cents=0,
                          priority="ESSENTIAL")
    get_success_data(api.financial_plan_state(plan["id"], "ACTIVATE", ADVISOR))
    data = validate_success(api.get_goal(goal["id"], ADVISOR))
    assert data["funded_ratio_bps"] == 10000, \
        f"PROJECTED variant on ACTIVE plan: 10000, got {data['funded_ratio_bps']}"
    assert data["on_track"] is True


# ===========================================================================
# Difficulty: boundary_precision_check / goal_on_track_at_exactly_100pct
# ===========================================================================
def test_goal_on_track_at_exactly_100_percent(api):
    """PRD §3.6: "The goal is `on_track` exactly when `funded_ratio_bps` is greater
    than or equal to 10000 — landing exactly at 100% counts as on track."

    Design: Difficulty/boundary_precision_check/goal_on_track_at_exactly_100pct
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    plan = fx.create_draft_plan(hh["id"], assumed_annual_return_bps=600,
                                monthly_contribution_cents=0)
    data = validate_success(api.create_goal(
        f.goal_payload(plan["id"], target_amount_cents=1000000,
                       target_date="2030-01-01", current_amount_cents=1000000),
        ADVISOR), expected_status=201)
    assert data["funded_ratio_bps"] == 10000, \
        f"current == target -> 10000, got {data['funded_ratio_bps']}"
    assert data["on_track"] is True


def test_goal_below_100_percent_not_on_track(api):
    """PRD §3.6: "`funded_ratio_bps` is that projected value multiplied by 10000
    and divided by `target_amount_cents`, rounded half up to whole basis points"

    DRAFT plan (ACTUAL): current 500,000 of target 1,000,000 -> 5000 bps, not on track.

    Design: Difficulty/boundary_precision_check/goal_on_track_at_exactly_100pct
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    plan = fx.create_draft_plan(hh["id"], assumed_annual_return_bps=600,
                                monthly_contribution_cents=0)
    data = validate_success(api.create_goal(
        f.goal_payload(plan["id"], target_amount_cents=1000000,
                       target_date="2030-01-01", current_amount_cents=500000),
        ADVISOR), expected_status=201)
    assert data["funded_ratio_bps"] == 5000, \
        f"500k of 1M -> 5000, got {data['funded_ratio_bps']}"
    assert data["on_track"] is False


# ===========================================================================
# Corner: calculations / goal_projected_with_return_variant
# ===========================================================================
def test_goal_projected_with_return_and_contributions(api):
    """PRD §3.6: "The future value of the current balance is `current_amount_cents`
    multiplied by one plus the monthly rate raised to the power of that month
    count. The future value of the contributions is `monthly_contribution_cents`
    multiplied by the standard annuity factor"

    Active plan, 6% return, 100,000/mo, 12 months, current 0 -> 1,233,556c projected
    == target 1,233,556c -> funded_ratio_bps 10000.

    Design: Corner/calculations/goal_projected_with_return_variant
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    plan = fx.create_draft_plan(assumed_annual_return_bps=600,
                                monthly_contribution_cents=100000)
    goal = fx.create_goal(plan["id"], target_amount_cents=1233556,
                          target_date="2027-03-01", current_amount_cents=0)
    get_success_data(api.financial_plan_state(plan["id"], "ACTIVATE", ADVISOR))
    data = validate_success(api.get_goal(goal["id"], ADVISOR))
    assert data["funded_ratio_bps"] == 10000, \
        f"projected 1,233,556 == target -> 10000, got {data['funded_ratio_bps']}"
