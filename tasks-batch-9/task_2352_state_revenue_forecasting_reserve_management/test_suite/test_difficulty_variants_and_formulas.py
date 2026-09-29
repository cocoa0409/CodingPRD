"""Variant-selector divergence and multi-step formula compliance.

Two calculations whose outcome is selected by a stored variant field
(`ForecastCycle.reconciliation_policy` and `ReserveFund.deposit_rule_variant`),
and three calculations whose pinned step order, tier ladder and evaluation order
decide the integer the API must report.

Every expected figure below is a literal taken from the frozen expectations in
`test_helpers.constants` or pinned inline; no test recomputes a value.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers import test_users as U

# --------------------------------------------------------------------------- #
# Pinned literals that are specific to these instances
# --------------------------------------------------------------------------- #
FUND_OPENING_EMPTY_CENTS = 0
GROWTH_MINUS_VOLATILE_DEPOSIT_CENTS = 15_836_326
COVERAGE_GROWTH_FUND_BPS = 2763
COVERAGE_VOLATILE_FUND_BPS = 770

CGT_RECURRING_COMPONENT_CENTS = 335_459_589

POLICY_UNCAPPED_TIER_PRODUCT_CENTS = 5_000_000
POLICY_WITH_FUTURE_CREDIT_CENTS = 13_000_000
POLICY_WITH_EXPIRED_WINDOW_CENTS = 11_000_000

MANUAL_DEPOSIT_TO_TARGET_CENTS = 7_487_677
MANUAL_DEPOSIT_MEMO = "Supplemental appropriation transfer to reach the statutory target exactly"
DISCLOSED_TARGET_STRONG_BPS = 300
REQUIRED_RESERVE_IF_CUSHION_FED_BACK_CENTS = 47_667_488
COVERAGE_IF_CUSHION_FED_BACK_BPS = 16687
ADEQUACY_HEADROOM_AT_TARGET_CENTS = 80_645_813


# --------------------------------------------------------------------------- #
# Local builders — every test builds its own state through the public API
# --------------------------------------------------------------------------- #
def _register_canonical_portfolio(api) -> Dict[str, Any]:
    """The two canonical sources with their two statutory policy changes.

    Policy adjustments hang off the source, so every cycle built afterwards sees
    them identically.
    """
    fx.set_clock(api, C.DEFAULT_CLOCK)
    pit = fx.create_pit_source(api)
    cgt = fx.create_cgt_source(api)
    fx.create_policy_adjustment(api, pit["id"], F.pit_policy_adjustment_payload())
    fx.create_policy_adjustment(api, cgt["id"], F.cgt_policy_adjustment_payload())
    return {"pit_source_id": pit["id"], "cgt_source_id": cgt["id"]}


def _compared_round_under_policy(
    api, portfolio: Dict[str, Any], reconciliation_policy: str
) -> Dict[str, Any]:
    """One FY2027 cycle carrying `reconciliation_policy`, taken to COMPARED.

    The two bodies file byte-identical inputs in every cycle built this way, so
    the only thing that can move `reconciled_total_cents` is the policy field.
    """
    pit_id = portfolio["pit_source_id"]
    cgt_id = portfolio["cgt_source_id"]
    cycle = fx.create_cycle(api, reconciliation_policy=reconciliation_policy)
    fx.add_canonical_scenarios(api, cycle["id"])
    fx.create_one_time_item(api, cycle["id"], cgt_id)
    fx.lock_inputs(api, cycle["id"])
    round_data = fx.open_round(api, cycle["id"])
    fx.file_estimate(api, round_data["id"], pit_id, "EXECUTIVE")
    fx.file_estimate(api, round_data["id"], cgt_id, "EXECUTIVE")
    fx.file_estimate(
        api,
        round_data["id"],
        pit_id,
        "LEGISLATIVE",
        judgmental_adjustment_cents=C.LEG_PIT_JUDGMENTAL_CENTS,
    )
    fx.file_estimate(
        api,
        round_data["id"],
        cgt_id,
        "LEGISLATIVE",
        judgmental_adjustment_cents=C.LEG_CGT_JUDGMENTAL_CENTS,
    )
    fx.submit_body(api, round_data["id"], "EXECUTIVE")
    compared = fx.submit_body(api, round_data["id"], "LEGISLATIVE")
    return {"cycle_id": cycle["id"], "round_id": round_data["id"], "round": compared}


def _scenario_estimate_preview(api, cycle_id: str, source_id: str) -> Dict[str, Any]:
    response = api.get_scenario_estimates(
        cycle_id, U.make_exec_economist_headers(), params={"source_id": source_id}
    )
    return validate_success(response, 200)


# =========================================================================== #
# dual_variant_calc — reconciliation policy on the consensus round
# =========================================================================== #
def test_reconciliation_policy_variants_diverge_on_reconciled_total(api):
    """PRD §3.5: "Otherwise the cycle's `reconciliation_policy` decides: under `MIDPOINT_AVERAGE`, the contribution is the executive and legislative amounts summed, divided by two and rounded half up, so the reconciled total normally sits between the two submissions; under `LOWER_OF_TWO`, the contribution is simply the lower of the two amounts, with no rounding performed at all, which means the reconciled total can equal neither body's own total when each body is the lower one on a different source."

    Design: Difficulty/dual_variant_calc/reconciliation_policy_variant_divergence_on_consensus_round
    """
    portfolio = _register_canonical_portfolio(api)
    midpoint = _compared_round_under_policy(api, portfolio, "MIDPOINT_AVERAGE")
    lower = _compared_round_under_policy(api, portfolio, "LOWER_OF_TWO")

    round_a = fx.read_round(api, midpoint["round_id"])
    round_b = fx.read_round(api, lower["round_id"])

    # Both rounds were fed byte-identical estimates: the two bodies' own totals
    # and the measured variance are the same on either policy.
    assert round_a["status"] == "COMPARED"
    assert round_b["status"] == "COMPARED"
    assert round_a["exec_total_cents"] == C.EXEC_TOTAL_CENTS
    assert round_b["exec_total_cents"] == C.EXEC_TOTAL_CENTS
    assert round_a["leg_total_cents"] == C.LEG_TOTAL_CENTS
    assert round_b["leg_total_cents"] == C.LEG_TOTAL_CENTS

    # Only the reconciled figure diverges.
    assert round_a["reconciled_total_cents"] == C.MIDPOINT_AVERAGE_RECONCILED_CENTS
    assert round_b["reconciled_total_cents"] == C.LOWER_OF_TWO_RECONCILED_CENTS
    assert (
        round_a["reconciled_total_cents"] - round_b["reconciled_total_cents"]
        == C.RECONCILIATION_POLICY_DELTA_CENTS
    )


def test_midpoint_average_reconciled_total_sits_between_the_two_submissions(api):
    """PRD §3.5: "`reconciled_total_cents` is the sum of the per-source contributions."

    PRD §3.5: "Otherwise the cycle's `reconciliation_policy` decides: under `MIDPOINT_AVERAGE`, the contribution is the executive and legislative amounts summed, divided by two and rounded half up, so the reconciled total normally sits between the two submissions; under `LOWER_OF_TWO`, the contribution is simply the lower of the two amounts, with no rounding performed at all, which means the reconciled total can equal neither body's own total when each body is the lower one on a different source."

    Design: Difficulty/dual_variant_calc/reconciliation_policy_variant_divergence_on_consensus_round
    """
    ctx = fx.full_chain(api, "compared", reconciliation_policy="MIDPOINT_AVERAGE")
    round_data = fx.read_round(api, ctx["round_id"])

    A.assert_round_comparison(
        round_data,
        status="COMPARED",
        exec_total_cents=C.EXEC_TOTAL_CENTS,
        leg_total_cents=C.LEG_TOTAL_CENTS,
        variance_bps=C.GRAND_VARIANCE_BPS,
        reconciled_total_cents=C.MIDPOINT_AVERAGE_RECONCILED_CENTS,
    )
    assert round_data["leg_total_cents"] < round_data["reconciled_total_cents"]
    assert round_data["reconciled_total_cents"] < round_data["exec_total_cents"]


def test_lower_of_two_reconciled_total_collapses_onto_the_legislative_total(api):
    """PRD §3.5: "Otherwise the cycle's `reconciliation_policy` decides: under `MIDPOINT_AVERAGE`, the contribution is the executive and legislative amounts summed, divided by two and rounded half up, so the reconciled total normally sits between the two submissions; under `LOWER_OF_TWO`, the contribution is simply the lower of the two amounts, with no rounding performed at all, which means the reconciled total can equal neither body's own total when each body is the lower one on a different source."

    Design: Difficulty/dual_variant_calc/reconciliation_policy_variant_divergence_on_consensus_round
    """
    ctx = fx.full_chain(api, "compared", reconciliation_policy="LOWER_OF_TWO")
    round_data = fx.read_round(api, ctx["round_id"])

    A.assert_round_comparison(
        round_data,
        status="COMPARED",
        exec_total_cents=C.EXEC_TOTAL_CENTS,
        leg_total_cents=C.LEG_TOTAL_CENTS,
        variance_bps=C.GRAND_VARIANCE_BPS,
        reconciled_total_cents=C.LOWER_OF_TWO_RECONCILED_CENTS,
    )
    # The legislative body is the lower one on both sources here, so the
    # unrounded per-source minima sum exactly to its own total.
    assert round_data["reconciled_total_cents"] == round_data["leg_total_cents"]
    assert round_data["reconciled_total_cents"] != C.MIDPOINT_AVERAGE_RECONCILED_CENTS


# =========================================================================== #
# dual_variant_calc — deposit rule variant on the reserve fund
# =========================================================================== #
def _certified_chain_with_both_deposit_variants(api) -> Dict[str, Any]:
    """One ratified FY2027 cycle plus two funds identical but for their variant,
    then certified so the deposit cascade runs against both."""
    ctx = fx.full_chain(api, "ratified")
    growth_fund = fx.create_fund(
        api,
        name="Budget Stabilization Fund",
        deposit_rule_variant="GROWTH_ABOVE_TREND",
        opening_balance_cents=FUND_OPENING_EMPTY_CENTS,
    )
    volatile_fund = fx.create_fund(
        api,
        name="Capital Gains Volatility Fund",
        deposit_rule_variant="VOLATILE_SOURCE_CAPTURE",
        opening_balance_cents=FUND_OPENING_EMPTY_CENTS,
    )
    ctx["cycle"] = fx.certify(api, ctx["cycle_id"])
    ctx["growth_fund_id"] = growth_fund["id"]
    ctx["volatile_fund_id"] = volatile_fund["id"]
    return ctx


def test_deposit_rule_variants_diverge_on_the_same_certification(api):
    """PRD §3.6: "Under `GROWTH_ABOVE_TREND`, the measured amount is the cycle's `certified_recurring_total_cents`, and the trend line is the cycle's `prior_recurring_baseline_cents` multiplied by 10000 plus the fund's `trend_growth_rate_bps`, divided by 10000, rounded half up."

    PRD §3.6: "Under `VOLATILE_SOURCE_CAPTURE`, only sources whose `volatility_class` is `HIGH` and whose `status` is `ACTIVE` count, and only their recurring part: the measured amount is the sum, over those sources, of each source's reconciled per-source value from the ratified round minus that source's `ACTIVE` one-time total."

    Design: Difficulty/dual_variant_calc/deposit_rule_variant_divergence_on_reserve_fund
    """
    ctx = _certified_chain_with_both_deposit_variants(api)

    A.assert_certified_aggregates(
        ctx["cycle"],
        total_cents=C.CERTIFIED_TOTAL_CENTS,
        one_time_cents=C.CERTIFIED_ONE_TIME_CENTS,
        recurring_cents=C.CERTIFIED_RECURRING_CENTS,
    )

    growth_fund = fx.read_fund(api, ctx["growth_fund_id"])
    volatile_fund = fx.read_fund(api, ctx["volatile_fund_id"])

    assert growth_fund["balance_cents"] == C.GROWTH_GROSS_COMPUTED_CENTS
    assert volatile_fund["balance_cents"] == C.VOLATILE_GROSS_COMPUTED_CENTS
    assert (
        growth_fund["balance_cents"] - volatile_fund["balance_cents"]
        == GROWTH_MINUS_VOLATILE_DEPOSIT_CENTS
    )
    assert growth_fund["deposit_posture"] == "ACCEPTING"
    assert volatile_fund["deposit_posture"] == "ACCEPTING"


def test_certification_deposit_rows_record_variant_specific_gross_amounts(api):
    """PRD §3.6: "A ledger row is minted **only when the deposited amount is greater than zero**, with `origin` `CERTIFICATION_DEPOSIT`, `signed_amount_cents` equal to the positive deposited amount, `source_cycle_id` pointing at the certifying cycle, and both `gross_computed_cents` and `overflow_returned_cents` recorded on the row; its `memo` is generated by the server, since no operator authored it."

    PRD §3.6: "`gross_computed_cents` is that excess multiplied by the fund's `capture_rate_bps`, divided by 10000, rounded half up: only the above-trend excess is captured, never the whole revenue level."

    Design: Difficulty/dual_variant_calc/deposit_rule_variant_divergence_on_reserve_fund
    """
    ctx = _certified_chain_with_both_deposit_variants(api)

    growth_rows = fx.list_transactions(api, fund_id=ctx["growth_fund_id"])
    volatile_rows = fx.list_transactions(api, fund_id=ctx["volatile_fund_id"])
    assert len(growth_rows) == 1
    assert len(volatile_rows) == 1

    A.assert_transaction_row(
        growth_rows[0],
        origin="CERTIFICATION_DEPOSIT",
        signed_amount_cents=C.GROWTH_GROSS_COMPUTED_CENTS,
        gross_computed_cents=C.GROWTH_GROSS_COMPUTED_CENTS,
        overflow_returned_cents=0,
        source_cycle_id=ctx["cycle_id"],
    )
    A.assert_transaction_row(
        volatile_rows[0],
        origin="CERTIFICATION_DEPOSIT",
        signed_amount_cents=C.VOLATILE_GROSS_COMPUTED_CENTS,
        gross_computed_cents=C.VOLATILE_GROSS_COMPUTED_CENTS,
        overflow_returned_cents=0,
        source_cycle_id=ctx["cycle_id"],
    )


def test_identical_cap_pct_yields_one_cap_but_two_coverage_ratios(api):
    """PRD §3.7: "`cap_cents` — the reference cycle's `certified_total_cents` multiplied by the fund's `cap_pct_bps`, divided by 10000, rounded half up."

    PRD §3.7: "`coverage_ratio_bps` — `balance_cents` multiplied by 10000, divided by `required_reserve_cents`, and **floored** so coverage is never overstated; it is 0 when `required_reserve_cents` is 0."

    Design: Difficulty/dual_variant_calc/deposit_rule_variant_divergence_on_reserve_fund
    """
    ctx = _certified_chain_with_both_deposit_variants(api)

    growth_fund = fx.read_fund(api, ctx["growth_fund_id"])
    volatile_fund = fx.read_fund(api, ctx["volatile_fund_id"])

    # Both funds share `cap_pct_bps` and the same reference cycle, so the
    # statutory ceiling and the required reserve are identical...
    assert growth_fund["cap_cents"] == C.FUND_CAP_CENTS
    assert volatile_fund["cap_cents"] == C.FUND_CAP_CENTS
    assert growth_fund["required_reserve_cents"] == C.ADEQUACY_REQUIRED_RESERVE_CENTS
    assert volatile_fund["required_reserve_cents"] == C.ADEQUACY_REQUIRED_RESERVE_CENTS

    # ...while the two variant-specific balances floor to two coverage ratios.
    assert growth_fund["coverage_ratio_bps"] == COVERAGE_GROWTH_FUND_BPS
    assert volatile_fund["coverage_ratio_bps"] == COVERAGE_VOLATILE_FUND_BPS


# =========================================================================== #
# combinatorial_formula — the scenario-weighted component's rounding order
# =========================================================================== #
def test_scenario_weighted_component_rounds_per_scenario_before_weighting(api):
    """PRD §3.4: "Then multiply each scenario's amount by that scenario's `weight_bps`, sum the products across all scenarios, divide by 10000, and round half up exactly once."

    PRD §3.4: "It is wrong to blend the growth rates first and apply one composite rate to the base year receipts: the per-scenario rounding at both steps is part of the specification, and the shortcut is off by tens of thousands of cents on a source of ordinary size."

    Design: Difficulty/combinatorial_formula/scenario_weighting_rounds_per_scenario_before_weighting
    """
    fx.set_clock(api, C.DEFAULT_CLOCK)
    pit = fx.create_pit_source(api)
    fx.create_policy_adjustment(api, pit["id"], F.pit_policy_adjustment_payload())
    cycle = fx.create_cycle(api)
    fx.add_canonical_scenarios(api, cycle["id"])

    preview = _scenario_estimate_preview(api, cycle["id"], pit["id"])

    assert preview["weighted_scenario_cents"] == C.PIT_WEIGHTED_SCENARIO_CENTS
    assert preview["weighted_scenario_cents"] != C.PIT_RATE_FIRST_SHORTCUT_CENTS


def test_scenario_estimate_preview_composes_the_pit_components(api):
    """PRD §3.9: "Alongside it, a second read-only view previews one source's numbers under a cycle's scenario weights before anything is filed: given a `source_id`, it runs the scenario-weighted blend and the policy phase-in without persisting anything, and returns `weighted_scenario_cents`, `policy_adjustment_cents`, `one_time_cents`, `recurring_component_cents` and `estimate_amount_cents` for that source."

    PRD §3.2: "The raw amount is `annualized_amount_cents` multiplied by that month count, divided by twelve, rounded half up."

    Design: Difficulty/combinatorial_formula/scenario_weighting_rounds_per_scenario_before_weighting
    """
    fx.set_clock(api, C.DEFAULT_CLOCK)
    pit = fx.create_pit_source(api)
    fx.create_policy_adjustment(api, pit["id"], F.pit_policy_adjustment_payload())
    cycle = fx.create_cycle(api)
    fx.add_canonical_scenarios(api, cycle["id"])

    preview = _scenario_estimate_preview(api, cycle["id"], pit["id"])

    assert preview["weighted_scenario_cents"] == C.PIT_WEIGHTED_SCENARIO_CENTS
    assert preview["policy_adjustment_cents"] == C.PIT_POLICY_ADJUSTMENT_CENTS
    assert preview["one_time_cents"] == 0
    assert preview["recurring_component_cents"] == C.EXEC_PIT_ESTIMATE_CENTS
    assert preview["estimate_amount_cents"] == C.EXEC_PIT_ESTIMATE_CENTS


# =========================================================================== #
# combinatorial_formula — the policy phase-in cap, tier ladder and windows
# =========================================================================== #
def _cgt_portfolio_with_three_adjustments(api) -> Dict[str, Any]:
    """One CGT source carrying a capped tiered increase, a future-year credit and
    an adjustment whose half-open window ends on the first day of FY2027."""
    fx.set_clock(api, C.DEFAULT_CLOCK)
    cgt = fx.create_cgt_source(api)
    tiered = fx.create_policy_adjustment(
        api,
        cgt["id"],
        F.policy_adjustment_payload(
            statute_code="SB-2027-003",
            policy_category="RATE_CHANGE",
            adjustment_kind="INCREASE",
            annualized_amount_cents=C.CGT_POLICY_ANNUALIZED_CENTS,
            effective_start_date="2026-07-01",
            effective_end_date=None,
            phase_in_type="TIERED",
            first_effective_fiscal_year=C.FISCAL_YEAR,
            cap_amount_cents=C.CGT_POLICY_CAP_CENTS,
        ),
    )
    future = fx.create_policy_adjustment(
        api,
        cgt["id"],
        F.policy_adjustment_payload(
            statute_code="SB-2028-021",
            policy_category="CREDIT",
            adjustment_kind="INCREASE",
            annualized_amount_cents=9_000_000,
            effective_start_date="2027-07-01",
            effective_end_date=None,
            phase_in_type="FULL",
            first_effective_fiscal_year=2028,
            cap_amount_cents=0,
        ),
    )
    expired = fx.create_policy_adjustment(
        api,
        cgt["id"],
        F.policy_adjustment_payload(
            statute_code="HB-2026-088",
            policy_category="COMPLIANCE",
            adjustment_kind="INCREASE",
            annualized_amount_cents=7_000_000,
            effective_start_date="2025-07-01",
            effective_end_date="2026-07-01",
            phase_in_type="FULL",
            first_effective_fiscal_year=2026,
            cap_amount_cents=0,
        ),
    )
    cycle = fx.create_cycle(api)
    fx.add_canonical_scenarios(api, cycle["id"])
    fx.create_one_time_item(api, cycle["id"], cgt["id"])
    return {
        "cgt_source_id": cgt["id"],
        "cycle_id": cycle["id"],
        "tiered_id": tiered["id"],
        "future_id": future["id"],
        "expired_id": expired["id"],
    }


def test_tiered_phase_in_cap_binds_over_the_first_year_tier_factor(api):
    """PRD §3.2: "With `phase_in_type` `TIERED`, subtract `first_effective_fiscal_year` from the target fiscal year to obtain a zero-based tier index, then take that index's phase-in factor from the statutory ladder of 2500, 5000, 7500 and 10000 basis points — a quarter of the annualised impact in the first year, a half in the second, three quarters in the third, and the full impact from the fourth year onward, an index above 3 being clamped to 3."

    PRD §3.2: "The cap is applied **after** rounding, never before: when `cap_amount_cents` is 0 the raw amount stands, and otherwise the amount is the lower of the raw amount and `cap_amount_cents`."

    Design: Difficulty/combinatorial_formula/policy_phase_in_cap_binds_over_tier_factor_and_window_guards
    """
    ctx = _cgt_portfolio_with_three_adjustments(api)

    preview = _scenario_estimate_preview(api, ctx["cycle_id"], ctx["cgt_source_id"])

    assert preview["policy_adjustment_cents"] == C.CGT_POLICY_ADJUSTMENT_CENTS
    assert preview["policy_adjustment_cents"] != POLICY_UNCAPPED_TIER_PRODUCT_CENTS


def test_out_of_window_adjustments_contribute_nothing_to_policy_adjustment(api):
    """PRD §3.2: "If `first_effective_fiscal_year` is greater than the target fiscal year, the adjustment contributes nothing."

    PRD §3.2: "If `effective_start_date` falls after the year's last day, or if `effective_end_date` is present and falls on or before the year's first day, the adjustment contributes nothing — the exclusive end boundary is why an end date equal to the year's first day contributes nothing."

    PRD §3.2: "The source's `policy_adjustment_cents` for that fiscal year is the sum of all such signed contributions."

    Design: Difficulty/combinatorial_formula/policy_phase_in_cap_binds_over_tier_factor_and_window_guards
    """
    ctx = _cgt_portfolio_with_three_adjustments(api)

    preview = _scenario_estimate_preview(api, ctx["cycle_id"], ctx["cgt_source_id"])

    # Only the capped tiered increase contributes: the FY2028 credit is beyond
    # the target year and the third window ends on FY2027's very first day.
    assert preview["policy_adjustment_cents"] == C.CGT_POLICY_ADJUSTMENT_CENTS
    assert preview["policy_adjustment_cents"] != POLICY_WITH_FUTURE_CREDIT_CENTS
    assert preview["policy_adjustment_cents"] != POLICY_WITH_EXPIRED_WINDOW_CENTS


def test_cgt_preview_folds_policy_and_one_time_into_the_two_sums(api):
    """PRD §3.4: "From these, `recurring_component_cents` is the sum of `weighted_scenario_cents`, `policy_adjustment_cents` and `judgmental_adjustment_cents`, and `estimate_amount_cents` is `recurring_component_cents` plus `one_time_cents`."

    PRD §3.4: "`one_time_cents` — the sum of `amount_cents` over the `ACTIVE` one-time items recorded for the round's cycle and this source."

    Design: Difficulty/combinatorial_formula/policy_phase_in_cap_binds_over_tier_factor_and_window_guards
    """
    ctx = _cgt_portfolio_with_three_adjustments(api)

    preview = _scenario_estimate_preview(api, ctx["cycle_id"], ctx["cgt_source_id"])

    assert preview["weighted_scenario_cents"] == C.CGT_WEIGHTED_SCENARIO_CENTS
    assert preview["policy_adjustment_cents"] == C.CGT_POLICY_ADJUSTMENT_CENTS
    assert preview["one_time_cents"] == C.ONE_TIME_AMOUNT_CENTS
    assert preview["recurring_component_cents"] == CGT_RECURRING_COMPONENT_CENTS
    assert preview["estimate_amount_cents"] == C.EXEC_CGT_ESTIMATE_CENTS


# =========================================================================== #
# combinatorial_formula — the adequacy disclosure's pinned evaluation order
# =========================================================================== #
def _fund_parked_at_the_strong_boundary(api) -> Dict[str, Any]:
    """A certified FY2027 cycle whose certification deposit plus one manual
    deposit lands the fund's balance exactly on its required reserve."""
    ctx = fx.full_chain(api, "certified", fund_overrides={})
    fund_before = fx.read_fund(api, ctx["fund_id"])
    assert fund_before["balance_cents"] == C.FUND_BALANCE_AFTER_DEPOSIT_CENTS
    ctx["manual_row"] = fx.deposit(
        api,
        ctx["fund_id"],
        MANUAL_DEPOSIT_TO_TARGET_CENTS,
        memo=MANUAL_DEPOSIT_MEMO,
    )
    return ctx


def test_required_reserve_uses_the_target_never_the_disclosed_target(api):
    """PRD §3.7: "`required_reserve_cents` — the reference cycle's `certified_recurring_total_cents` multiplied by `target_pct_bps`, divided by 10000, rounded half up."

    PRD §3.7: "This is a disclosure figure only and is **never** fed back into step three, so a strong fund never becomes non-strong on the strength of its own cushion credit."

    Design: Difficulty/combinatorial_formula/adequacy_disclosure_order_pinned_against_circular_cushion_credit
    """
    ctx = _fund_parked_at_the_strong_boundary(api)

    disclosure = fx.read_adequacy(api, ctx["fund_id"])

    assert disclosure["volatility_index_bps"] == 0
    assert disclosure["target_pct_bps"] == C.TARGET_BAND_LOW_BPS
    assert disclosure["required_reserve_cents"] == C.ADEQUACY_REQUIRED_RESERVE_CENTS
    # Feeding the disclosed target back into step three would shrink it here.
    assert disclosure["required_reserve_cents"] != REQUIRED_RESERVE_IF_CUSHION_FED_BACK_CENTS


def test_coverage_at_the_exact_strong_boundary_earns_the_cushion_credit(api):
    """PRD §3.7: "`adequacy_band` — `STRONG` when `coverage_ratio_bps` is at least 10000 (the fund fully covers its requirement), `ADEQUATE` when it is at least 6000, `THIN` when it is at least 3000, and `INSUFFICIENT` below that."

    PRD §3.7: "`cushion_credit_bps` — 200 basis points when `adequacy_band` is `STRONG`, and 0 in every other band."

    Design: Difficulty/combinatorial_formula/adequacy_disclosure_order_pinned_against_circular_cushion_credit
    """
    ctx = _fund_parked_at_the_strong_boundary(api)

    fund = fx.read_fund(api, ctx["fund_id"])
    assert fund["balance_cents"] == C.ADEQUACY_BALANCE_STRONG_EXACT_CENTS

    disclosure = fx.read_adequacy(api, ctx["fund_id"])
    assert disclosure["coverage_ratio_bps"] == C.ADEQUACY_COVERAGE_STRONG_EXACT_BPS
    # A second pass on a re-fed target would re-score coverage upward.
    assert disclosure["coverage_ratio_bps"] != COVERAGE_IF_CUSHION_FED_BACK_BPS
    assert disclosure["adequacy_band"] == "STRONG"
    assert disclosure["cushion_credit_bps"] == C.CUSHION_CREDIT_BPS
    assert disclosure["disclosed_target_pct_bps"] == DISCLOSED_TARGET_STRONG_BPS


def test_manual_deposit_row_and_remaining_cap_headroom_at_the_target(api):
    """PRD §3.7: "The posting mints a ledger row with `origin` `MANUAL_DEPOSIT`, `signed_amount_cents` equal to the positive `amount_cents`, `gross_computed_cents` equal to the same amount and `overflow_returned_cents` 0; the fund's `balance_cents` rises by that amount, `last_transaction_at` becomes the row's `created_at`, the adequacy disclosure is re-derived, `deposit_posture` may flip `ACCEPTING → AT_CAP`, every `PUBLISHED` briefing of the fund goes `STALE` with `stale_reason` `RESERVE_BALANCE_CHANGED`, and the fund's `version` increments by one."

    PRD §3.7: "A read-only companion view reports the same disclosure without persisting anything, naming the `reference_cycle_id` it used together with `volatility_index_bps`, `target_pct_bps`, `required_reserve_cents`, `coverage_ratio_bps`, `adequacy_band`, `cushion_credit_bps`, `disclosed_target_pct_bps`, `cap_cents`, the deposit `headroom_cents` left under the cap, and the withdrawal room left this fiscal year as `annual_withdrawal_cap_cents` and `cap_headroom_cents`."

    Design: Difficulty/combinatorial_formula/adequacy_disclosure_order_pinned_against_circular_cushion_credit
    """
    ctx = _fund_parked_at_the_strong_boundary(api)

    A.assert_transaction_row(
        ctx["manual_row"],
        origin="MANUAL_DEPOSIT",
        signed_amount_cents=MANUAL_DEPOSIT_TO_TARGET_CENTS,
        gross_computed_cents=MANUAL_DEPOSIT_TO_TARGET_CENTS,
        overflow_returned_cents=0,
    )

    disclosure = fx.read_adequacy(api, ctx["fund_id"])
    assert disclosure["cap_cents"] == C.FUND_CAP_CENTS
    assert disclosure["headroom_cents"] == ADEQUACY_HEADROOM_AT_TARGET_CENTS

    fund = fx.read_fund(api, ctx["fund_id"])
    assert fund["balance_cents"] == C.ADEQUACY_BALANCE_STRONG_EXACT_CENTS
    assert fund["deposit_posture"] == "ACCEPTING"
