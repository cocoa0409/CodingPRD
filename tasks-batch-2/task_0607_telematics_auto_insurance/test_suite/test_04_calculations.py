"""Risk-scoring, multiplier-tier, premium, and discount calculation tests.

Translated from SCAFFOLD_DIFFICULTY_DESIGN.yaml queue A rules `dual_variant_calc`
and `combinatorial_formula`, and SCAFFOLD_CORNER_DESIGN.yaml queue B section
`calculations`.
"""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    create_statement_payload,
    create_renewal_payload,
    create_claim_payload,
    triage_claim_payload,
    TEST_USERS,
    set_clock,
    create_rate_plan,
    create_driver,
    create_enrollment,
    add_three_clean_scoring_trips,
    finalize_scoring,
    create_quote,
    bind_policy,
    driver_headers,
    add_policy_trip,
    hard_brake_events,
    get_policy,
    get_enrollment,
    get_discount_bank,
    setup_dual_variant_divergence,
    setup_elevated_quote,
    setup_rounding_policy_standard_mult,
    setup_bound_policy_with_standard_score,
)

UW = TEST_USERS["underwriting_headers"]
CLAIMS = TEST_USERS["claims_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: dual_variant_calc
#   instance: provisional_vs_operational_risk_diverge_on_same_events (>= 2 tests)
# ─────────────────────────────────────────────────────────────────────────────

def test_provisional_score_normalizes_per_100_miles(api):
    """PRD §3.3: "Form a per-100-mile factor equal to 100 divided by the total
    mileage. Multiply the plan's `hard_brake_weight` by the hard-brake total scaled by
    that per-100-mile factor, the plan's `speeding_weight` by the speeding total scaled
    by the same factor, and the plan's `phone_use_weight` by the phone-use total scaled
    by the same factor; add the three products together and round the sum half-up to
    two decimal places."

    Design: Difficulty/dual_variant_calc/provisional_vs_operational_risk_diverge_on_same_events
    """
    ctx = setup_dual_variant_divergence()
    enrollment = get_enrollment(ctx)
    # hb=4 sp=2 pu=1 over 40 miles -> 2.0*10 + 1.5*5 + 1.0*2.5 = 30.0
    assert enrollment["provisional_risk_score"] == pytest.approx(30.0, abs=0.001)


def test_operational_score_uses_absolute_counts_diverges_from_provisional(api):
    """PRD §3.5: "Unlike the provisional variant, these counts are absolute and are
    not normalized per 100 miles, so identical trips produce a different number from
    the provisional score."
    PRD §2.7: "the provisional score divides by mileage while the operational score
    does not".

    Design: Difficulty/dual_variant_calc/provisional_vs_operational_risk_diverge_on_same_events
    """
    ctx = setup_dual_variant_divergence()
    enrollment = get_enrollment(ctx)
    policy = get_policy(ctx)
    # same hb=4 sp=2 pu=1 absolute -> 2.0*4 + 1.5*2 + 1.0*1 = 12.0
    assert policy["current_risk_score"] == pytest.approx(12.0, abs=0.001)
    assert enrollment["provisional_risk_score"] != policy["current_risk_score"]


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: dual_variant_calc
#   instance: quoted_premium_vs_claim_reserve_independent_domains (>= 2 tests)
# ─────────────────────────────────────────────────────────────────────────────

def test_quoted_premium_is_base_times_multiplier(api):
    """PRD §3.4: "It then computes `quoted_annual_premium_cents` as the plan's
    `base_premium_cents` multiplied by that `risk_multiplier`, rounded half-up to the
    whole cent."

    Design: Difficulty/dual_variant_calc/quoted_premium_vs_claim_reserve_independent_domains
    """
    ctx = setup_elevated_quote()
    quote = ctx["quote"]
    # locked_risk_score 30.0 -> ELEVATED 1.25 -> 200000 * 1.25 = 250000
    assert quote["locked_risk_score"] == pytest.approx(30.0, abs=0.001)
    assert quote["quoted_annual_premium_cents"] == 250000


def test_claim_reserve_is_severity_scaled_independent_of_premium(api):
    """PRD §3.8: "Triage sets the loss reserve: `reserve_cents` is the reserve base of
    100000 cents multiplied by the claim's `reported_severity`."

    Design: Difficulty/dual_variant_calc/quoted_premium_vs_claim_reserve_independent_domains
    """
    ctx = setup_elevated_quote()
    policy = bind_policy(ctx["quote"])
    claim = get_success_data(api.create_claim(
        create_claim_payload(policy["id"], reported_severity=4, reason="rear-end"),
        ctx["dheaders"]))
    triaged = get_success_data(api.triage_claim(claim["id"], triage_claim_payload(), CLAIMS))
    # 100000 * 4 = 400000, unrelated to the 250000 premium figure
    assert triaged["reserve_cents"] == 400000


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: combinatorial_formula
#   instance: risk_multiplier_tier_selection_nonlinear_three_inputs (>= 2 tests)
# ─────────────────────────────────────────────────────────────────────────────

def test_risk_multiplier_lands_in_elevated_tier(api):
    """PRD §2.8: "A score of at least 25.0 but strictly below 50.0 lands in the
    ELEVATED tier and yields 1.25."

    Design: Difficulty/combinatorial_formula/risk_multiplier_tier_selection_nonlinear_three_inputs
    """
    ctx = setup_elevated_quote()
    quote = ctx["quote"]
    assert quote["locked_risk_score"] == pytest.approx(30.0, abs=0.001)
    assert quote["risk_multiplier"] == pytest.approx(1.25, abs=0.001)


def test_risk_multiplier_premium_reflects_elevated_tier(api):
    """PRD §2.8: "A score of at least 25.0 but strictly below 50.0 lands in the
    ELEVATED tier and yields 1.25."
    PRD §3.4: "It then computes `quoted_annual_premium_cents` as the plan's
    `base_premium_cents` multiplied by that `risk_multiplier`, rounded half-up to the
    whole cent."

    Design: Difficulty/combinatorial_formula/risk_multiplier_tier_selection_nonlinear_three_inputs
    """
    ctx = setup_elevated_quote()
    quote = ctx["quote"]
    # ELEVATED tier multiplier 1.25 -> 200000 * 1.25 = 250000
    assert quote["risk_multiplier"] == pytest.approx(1.25, abs=0.001)
    assert quote["quoted_annual_premium_cents"] == 250000


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: combinatorial_formula
#   instance: mileage_premium_round_per_component_then_sum (>= 2 tests)
# ─────────────────────────────────────────────────────────────────────────────

def test_mileage_premium_rounds_each_component_independently(api):
    """PRD §3.6: "take the policy's `bound_premium_cents` divided by the periods-per-year
    constant of 12, multiply by the policy's `current_risk_multiplier`, and round that
    single component half-up to a whole cent to obtain `base_charge_cents`. The mileage
    charge is `overage_miles` multiplied by the plan's `per_mile_rate_cents`, rounded
    half-up to a whole cent on its own to obtain `mileage_charge_cents`."

    Design: Difficulty/combinatorial_formula/mileage_premium_round_per_component_then_sum
    """
    ctx = setup_rounding_policy_standard_mult()
    p_ver = get_policy(ctx)["version"]
    statement = get_success_data(api.create_statement(
        create_statement_payload(ctx["policy"]["id"], p_ver), UW))
    # bound 86706, mult 1.0 -> base_raw 7225.5 -> 7226
    # overage 3001 (billed 4001 - included 1000) * 0.5 = 1500.5 -> 1501
    assert statement["base_charge_cents"] == 7226
    assert statement["mileage_charge_cents"] == 1501


def test_mileage_premium_per_component_sum_beats_sum_then_round(api):
    """PRD §3.6: "The two components are rounded **independently first and only then
    summed** — this round-per-component-then-sum order is deliberate and differs from
    summing the raw amounts before a single rounding whenever both components carry
    fractional cents."

    Design: Difficulty/combinatorial_formula/mileage_premium_round_per_component_then_sum
    """
    ctx = setup_rounding_policy_standard_mult()
    p_ver = get_policy(ctx)["version"]
    statement = get_success_data(api.create_statement(
        create_statement_payload(ctx["policy"]["id"], p_ver), UW))
    # per-component: 7226 + 1501 == 8727 (sum-then-round would give 8726)
    assert statement["base_charge_cents"] + statement["mileage_charge_cents"] == 8727


# ─────────────────────────────────────────────────────────────────────────────
# Corner: calculations
# ─────────────────────────────────────────────────────────────────────────────

def test_discount_redemption_caps_at_statement_total(api):
    """PRD §3.6: "The applied discount is then the lesser of the discount bank's
    `available_cents` and that pre-discount total, so the bill can never be discounted
    below zero; this value becomes `applied_discount_cents`. The `total_due_cents` is
    the pre-discount total minus `applied_discount_cents`, which is non-negative by
    construction."
    PRD §3.6: "On settlement the statement moves to `SETTLED`, the discount bank's
    `redeemed_cents` increases by `applied_discount_cents`, and a redeem-leg grant is
    appended."

    Design: Corner/calculations/discount_redemption_caps_at_statement_total
    """
    set_clock("2026-03-01T00:00:00Z")
    rate_plan = create_rate_plan(name="Round Plan", base_premium_cents=102007,
                                 per_mile_rate_cents=0.5, included_miles_per_period=1000,
                                 hard_brake_weight=2.0, speeding_weight=0.0, phone_use_weight=0.0)
    driver = create_driver()
    enrollment = create_enrollment(driver, rate_plan, 30)
    add_three_clean_scoring_trips(driver, enrollment, day="2026-03-01")
    finalize_scoring(driver, enrollment)
    quote = create_quote(enrollment)
    policy = bind_policy(quote)
    ctx = {"driver": driver, "rate_plan": rate_plan, "enrollment": enrollment,
           "quote": quote, "policy": policy, "dheaders": driver_headers(driver)}
    # clean 5-mile trip earns 250 in the bank and contributes 5 miles to the period
    add_policy_trip(ctx, "2026-03-02T01:00:00Z", "2026-03-02T01:30:00Z", 5.0, accept=True)
    # 4001-mile hb=6 trip -> operational 12.0 (STANDARD, mult 1.0)
    add_policy_trip(ctx, "2026-03-02T02:00:00Z", "2026-03-02T08:00:00Z", 4001.0,
                    events=hard_brake_events(6, day="2026-03-02", base_hour="02"), accept=True)
    p_ver = get_policy(ctx)["version"]
    statement = get_success_data(api.create_statement(
        create_statement_payload(policy["id"], p_ver), UW))
    get_success_data(api.issue_statement(statement["id"], UW))
    settled = get_success_data(api.settle_statement(statement["id"], UW))
    # billed_miles 4006 -> overage 3006 -> mileage round(1503.0)=1503; base 7226; total 8729
    # available 250 -> applied 250 -> total_due 8479
    assert settled["applied_discount_cents"] == 250
    assert settled["total_due_cents"] == 8479
    bank = get_discount_bank(ctx)
    assert bank["available_cents"] == 0
    assert bank["redeemed_cents"] == 250


def test_renewal_premium_recalculates_from_current_score(api):
    """PRD §3.9: "snapshots the policy's `current_risk_score` into
    `recalculated_risk_score`, and derives a renewal multiplier from that score via the
    tier table. From there it computes `recalculated_premium_cents` as the plan's
    `base_premium_cents` multiplied by the renewal multiplier, rounded half-up to the
    whole cent."

    Design: Corner/calculations/renewal_premium_recalculates_from_current_score
    """
    ctx, _trip = setup_bound_policy_with_standard_score(
        clock="2026-03-01T00:00:00Z", scoring_day="2026-03-01",
        drive_day="2026-03-05", distance=30.0)
    p_ver = get_policy(ctx)["version"]
    renewal = get_success_data(api.create_renewal(
        create_renewal_payload(ctx["policy"]["id"], p_ver), UW))
    # current_risk_score 12.0 -> STANDARD 1.0 -> 200000 * 1.0 = 200000
    assert renewal["recalculated_risk_score"] == pytest.approx(12.0, abs=0.001)
    assert renewal["recalculated_premium_cents"] == 200000
