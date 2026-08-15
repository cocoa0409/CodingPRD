"""Scenario financial outputs: debt sizing constraint binding (PRD §3.5) and
waterfall promote splits (PRD §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_debt_sizing,
    assert_waterfall,
    create_debt_sizing_payload,
    create_waterfall_payload,
    expected_total_distributions_cents,
    setup_canonical_computed_scenario,
    setup_computed_scenario,
    setup_negative_noi_scenario,
    validate_error,
    validate_success,
)

PRICE = 1_000_000_000
GP_EQUITY_CENTS = 100_000_000  # 10% of the price — "GP equity is the remainder" (PRD §3.6)


def test_debt_sizing_ltv_constraint_binds(api, analyst_headers):
    """PRD §3.5: "The DSCR-constrained maximum loan is the year-one NOI divided by
    the product of `min_dscr_pct` divided by 100 and the annual debt service per
    dollar. The LTV-constrained maximum loan is the deal's
    `target_purchase_price_cents` multiplied by `max_ltv_pct` divided by 100. The
    sized `loan_amount_cents` is the smaller of the two maxima, floored to
    integer cents."
    PRD §3.5: "If the absolute difference between the DSCR-constrained maximum and
    the LTV-constrained maximum is less than one cent, the sizing is recorded as
    `BOTH`. Otherwise, if the DSCR maximum is strictly less than the LTV maximum,
    the sizing is `DSCR`; otherwise it is `LTV`."
    PRD §3.5: "`ltv_at_size_pct` is the sized loan divided by
    `target_purchase_price_cents`, multiplied by 100, and rounded to the nearest
    whole percent."
    With a cheap 550 bps / 30-year loan and a loose 125% DSCR floor, the
    DSCR-bound maximum far exceeds 65% of the 1_000_000_000-cent price, so LTV
    binds at exactly 650_000_000 cents.

    Design: Difficulty/dual_variant_calc/debt_sizing_dscr_vs_ltv_binding
    """
    env = setup_canonical_computed_scenario(deal_code="D-DEBT")
    scen_id = env["scenario"]["id"]
    ds = validate_success(
        api.create_debt_sizing(
            scen_id,
            create_debt_sizing_payload(
                interest_rate_bps=550, amortization_years=30, io_months=12,
                min_dscr_pct=125, max_ltv_pct=65,
            ),
            analyst_headers,
        ),
        201,
    )
    assert_debt_sizing(ds)
    assert ds["loan_amount_cents"] == 650_000_000, (
        f"LTV-bound size must be 0.65 * price = 650000000, got {ds['loan_amount_cents']}"
    )
    assert ds["sizing_constraint"] == "LTV", (
        f"expected LTV to bind, got {ds['sizing_constraint']}"
    )
    assert ds["ltv_at_size_pct"] == 65


def test_debt_sizing_dscr_constraint_binds(api, analyst_headers):
    """PRD §3.5: "The sized `loan_amount_cents` is the smaller of the two maxima,
    floored to integer cents."
    PRD §3.5: "Otherwise, if the DSCR maximum is strictly less than the LTV
    maximum, the sizing is `DSCR`; otherwise it is `LTV`."
    PRD §3.5: "`dscr_at_size_pct` is the year-one NOI divided by the product of
    the sized loan and the annual debt service per dollar — a decimal converted
    to a whole percent."
    With an expensive 800 bps / 25-year loan and a tight 150% DSCR floor, the
    DSCR-bound maximum lands far below both the 75% LTV cap and the LTV-bound
    size from the cheap-money case; the sized loan sits exactly on the DSCR
    floor, so the realized DSCR rounds to 150.

    Design: Difficulty/dual_variant_calc/debt_sizing_dscr_vs_ltv_binding
    """
    env = setup_canonical_computed_scenario(deal_code="D-DEBT2")
    scen_id = env["scenario"]["id"]
    cheap = validate_success(
        api.create_debt_sizing(
            scen_id,
            create_debt_sizing_payload(
                interest_rate_bps=550, amortization_years=30, io_months=12,
                min_dscr_pct=125, max_ltv_pct=65,
            ),
            analyst_headers,
        ),
        201,
    )
    tight = validate_success(
        api.create_debt_sizing(
            scen_id,
            create_debt_sizing_payload(
                interest_rate_bps=800, amortization_years=25, io_months=0,
                min_dscr_pct=150, max_ltv_pct=75,
            ),
            analyst_headers,
        ),
        201,
    )
    assert_debt_sizing(tight)
    assert tight["sizing_constraint"] == "DSCR", (
        f"expected DSCR to bind, got {tight['sizing_constraint']}"
    )
    assert tight["loan_amount_cents"] < cheap["loan_amount_cents"], (
        f"DSCR-bound size {tight['loan_amount_cents']} must be below the "
        f"LTV-bound size {cheap['loan_amount_cents']}"
    )
    assert tight["dscr_at_size_pct"] == 150, (
        f"DSCR binds at exactly the floor: expected 150, got {tight['dscr_at_size_pct']}"
    )


def test_debt_sizing_nonpositive_noi_rejected(api, analyst_headers):
    """PRD §3.5: "Debt sizing requires the scenario's `computed_noi_yr1_cents` to
    be positive. If it is zero or negative, the request is rejected with
    `ERR_NOI_NONPOSITIVE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/business_fiscal_vs_business_safety_on_debt_sizing
    """
    env = setup_negative_noi_scenario()
    assert env["scenario"]["status"] == "COMPUTED"
    assert env["scenario"]["computed_noi_yr1_cents"] <= 0, (
        f"setup must produce a non-positive NOI, got {env['scenario']['computed_noi_yr1_cents']}"
    )
    res = api.create_debt_sizing(
        env["scenario"]["id"],
        create_debt_sizing_payload(
            interest_rate_bps=600, amortization_years=30, io_months=0,
            min_dscr_pct=125, max_ltv_pct=65,
        ),
        analyst_headers,
    )
    validate_error(res, ApiErrorId.ERR_NOI_NONPOSITIVE)


def test_waterfall_regressive_promote_rejected(api, analyst_headers):
    """PRD §3.6: "A regressive promote structure — one where `promote_tier2_bps`
    is less than `promote_tier1_bps` — is rejected with `ERR_PROMOTE_REGRESSIVE`
    (HTTP 422)."

    Design: Corner/validations/promote_tier2_less_than_tier1_rejected
    """
    env = setup_computed_scenario(deal_overrides={"deal_code": "D-WF2"})
    res = api.create_waterfall(
        env["scenario"]["id"],
        create_waterfall_payload(
            pref_return_bps=800, promote_tier1_bps=3000,
            tier1_hurdle_bps=1200, promote_tier2_bps=2000,
        ),
        analyst_headers,
    )
    validate_error(res, ApiErrorId.ERR_PROMOTE_REGRESSIVE)


def test_waterfall_conserves_total_distributions(api, analyst_headers):
    """PRD §3.6: "Total distributions are the sum of every projected year-NOI
    across the hold plus the exit value."
    PRD §3.6: "The split is computed in tiers, each tier rounded half-up to
    integer cents before the next tier is computed — tier rounding is locked in
    sequence."
    The LP and GP legs must together return every cent the projection produced:
    lp_split_cents + gp_split_cents equals the total distributions implied by
    the scenario's computed NOI (within the per-tier rounding dust the PRD
    licenses).

    Design: Difficulty/combinatorial_formula/waterfall_tier_rounding_locked_per_tier
    """
    env = setup_canonical_computed_scenario(deal_code="D-WF")
    scenario = env["scenario"]
    wf = validate_success(
        api.create_waterfall(
            scenario["id"],
            create_waterfall_payload(
                pref_return_bps=800, promote_tier1_bps=2000,
                tier1_hurdle_bps=1200, promote_tier2_bps=3000,
            ),
            analyst_headers,
        ),
        201,
    )
    assert_waterfall(wf)
    total = expected_total_distributions_cents(
        scenario["computed_noi_yr1_cents"],
        steady_growth_bps=300, hold_years=5, exit_cap_bps=550,
    )
    assert wf["lp_split_cents"] + wf["gp_split_cents"] == pytest.approx(total, abs=2), (
        f"cash conservation violated: {wf['lp_split_cents']} + {wf['gp_split_cents']} "
        f"!= {total}"
    )


def test_waterfall_promote_is_gp_split_above_gp_equity(api, analyst_headers):
    """PRD §3.6: "LP equity is the deal's `target_purchase_price_cents`
    multiplied by 0.90; GP equity is the remainder."
    PRD §3.6: "The waterfall writes three outputs: `lp_split_cents` is LP equity
    plus `lp_pref` plus `lp_tier1` plus `lp_tier2`; `gp_split_cents` is GP equity
    plus `gp_tier1` plus `gp_tier2`; and `gp_promote_cents` is `gp_tier1` plus
    `gp_tier2` — the carried-interest portion of the GP's distribution."

    Design: Difficulty/combinatorial_formula/waterfall_tier_rounding_locked_per_tier
    """
    env = setup_canonical_computed_scenario(deal_code="D-WF3")
    wf = validate_success(
        api.create_waterfall(
            env["scenario"]["id"],
            create_waterfall_payload(
                pref_return_bps=800, promote_tier1_bps=2000,
                tier1_hurdle_bps=1200, promote_tier2_bps=3000,
            ),
            analyst_headers,
        ),
        201,
    )
    assert_waterfall(wf)
    assert wf["gp_promote_cents"] == wf["gp_split_cents"] - GP_EQUITY_CENTS, (
        f"promote must be exactly the GP split above GP equity: "
        f"{wf['gp_promote_cents']} != {wf['gp_split_cents']} - {GP_EQUITY_CENTS}"
    )


def test_waterfall_conservation_under_alternate_params(api, analyst_headers):
    """PRD §3.6: "Total distributions are the sum of every projected year-NOI
    across the hold plus the exit value."
    PRD §3.6: "The split is computed in tiers, each tier rounded half-up to
    integer cents before the next tier is computed — tier rounding is locked in
    sequence."
    Conservation is a property of the split, not of one parameter choice: a
    lower pref and lower promotes conserve the same total.

    Design: Difficulty/compensating_invariant/waterfall_split_conserves_total_distributions
    """
    env = setup_canonical_computed_scenario(deal_code="D-INV2")
    scenario = env["scenario"]
    wf = validate_success(
        api.create_waterfall(
            scenario["id"],
            create_waterfall_payload(
                pref_return_bps=600, promote_tier1_bps=1500,
                tier1_hurdle_bps=1000, promote_tier2_bps=2500,
            ),
            analyst_headers,
        ),
        201,
    )
    assert_waterfall(wf)
    total = expected_total_distributions_cents(
        scenario["computed_noi_yr1_cents"],
        steady_growth_bps=300, hold_years=5, exit_cap_bps=550,
    )
    assert wf["lp_split_cents"] + wf["gp_split_cents"] == pytest.approx(total, abs=2), (
        f"cash conservation violated under alternate params: "
        f"{wf['lp_split_cents']} + {wf['gp_split_cents']} != {total}"
    )


def test_waterfall_promote_bounded_by_gp_excess(api, analyst_headers):
    """PRD §3.6: "LP equity is the deal's `target_purchase_price_cents`
    multiplied by 0.90; GP equity is the remainder."
    PRD §3.6: "The waterfall writes three outputs: `lp_split_cents` is LP equity
    plus `lp_pref` plus `lp_tier1` plus `lp_tier2`; `gp_split_cents` is GP equity
    plus `gp_tier1` plus `gp_tier2`; and `gp_promote_cents` is `gp_tier1` plus
    `gp_tier2` — the carried-interest portion of the GP's distribution."
    The promote is exactly the GP's take above its contributed equity — never
    negative, never more than the GP split minus GP equity — and the waterfall
    creates no cash: lp_split + gp_split conserves the projected total.

    Design: Difficulty/compensating_invariant/waterfall_split_conserves_total_distributions
    """
    env = setup_canonical_computed_scenario(deal_code="D-INV3")
    scenario = env["scenario"]
    wf = validate_success(
        api.create_waterfall(
            scenario["id"],
            create_waterfall_payload(
                pref_return_bps=600, promote_tier1_bps=1500,
                tier1_hurdle_bps=1000, promote_tier2_bps=2500,
            ),
            analyst_headers,
        ),
        201,
    )
    assert_waterfall(wf)
    assert wf["gp_promote_cents"] >= 0
    assert wf["gp_promote_cents"] == wf["gp_split_cents"] - GP_EQUITY_CENTS
    total = expected_total_distributions_cents(
        scenario["computed_noi_yr1_cents"],
        steady_growth_bps=300, hold_years=5, exit_cap_bps=550,
    )
    assert wf["lp_split_cents"] + wf["gp_split_cents"] == pytest.approx(total, abs=2)
