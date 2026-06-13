"""Premium accrual, the conserved subsidy ledger, and agent commissions.

Covers per-acre-then-sum rounding order (PRD §3.4), the subsidy-factor table lookup,
the commission tier ladder keyed on the finalized total (PRD §3.8), the conserved
ledger invariant, and ledger reconciliation after a void.
"""
import pytest
from test_helpers import (
    validate_success, get_success_data, assert_premium_conserved,
    setup_policy_with_election, setup_election_with_unit, setup_activated_policy,
    add_unit,
)


def test_premium_rounds_per_acre_before_summing(api):
    """PRD §3.4: "The per-acre premium in cents is the product of those three, rounded
    to a whole number of cents. This rounding to whole cents happens first, before any
    acreage is applied."
    PRD §3.4: "Because each unit is rounded before summing, the order is
    round-per-unit-then-sum, never sum-then-round."

    Design: Difficulty/combinatorial_formula/combinatorial_premium_rounding_order_per_acre_then_sum
    """
    # RP, liability 54000c/ac, base 0.085, RP mult 1.15:
    #   per_acre raw = 54000*0.085*1.15 = 5278.5 -> round half-up -> 5279c
    #   unit = round(5279 * 100 * 1) = 527900c. (sum-then-round would give 527850.)
    ctx = setup_policy_with_election(plan_type="RP", aph_yield=180, coverage_level=0.75,
                                     base_premium_rate=0.085)
    add_unit(ctx["election"]["id"], ctx["sa_headers"], acres=100, share=1)
    elec = get_success_data(api.get_coverage_election(ctx["election"]["id"], ctx["sa_headers"]))
    assert elec["dollar_liability_per_acre_cents"] == 54000, elec["dollar_liability_per_acre_cents"]
    assert elec["total_premium_cents"] == 527900, elec["total_premium_cents"]


def test_premium_round_per_unit_then_sum_across_units(api):
    """PRD §3.4: "Each unit's premium contribution is then that rounded per-acre figure
    multiplied by the unit's acres and its share, again rounded to a whole number of cents.
    The election's total_premium_cents is the sum of those per-unit contributions across
    every unit under the election"

    Design: Difficulty/combinatorial_formula/combinatorial_premium_rounding_order_per_acre_then_sum
    """
    # RP per-acre rounds to 5279c. Two 100-ac share=1 units: each unit = 527900c;
    #   total = 527900 + 527900 = 1055800 (round-per-unit-then-sum).
    ctx = setup_policy_with_election(plan_type="RP", aph_yield=180, coverage_level=0.75,
                                     base_premium_rate=0.085)
    add_unit(ctx["election"]["id"], ctx["sa_headers"], unit_number="0001-0001", acres=100, share=1)
    add_unit(ctx["election"]["id"], ctx["sa_headers"], unit_number="0001-0002", acres=100, share=1)
    elec = get_success_data(api.get_coverage_election(ctx["election"]["id"], ctx["sa_headers"]))
    assert elec["total_premium_cents"] == 1055800, elec["total_premium_cents"]


def test_commission_tier_keyed_on_finalized_total_premium(api):
    """PRD §3.8: "Its commission_rate is selected by tier from the election's finalized
    total_premium_cents — and because the tier is keyed on the very total it scales, the
    premium total must be finalized before the tier is chosen."
    PRD §3.8: "if it is at least 500000 cents and at most 1000000 cents (five thousand
    through ten thousand dollars, inclusive), the rate is 0.08"
    PRD §3.8: "The commission_cents is the election's total_premium_cents multiplied by
    the selected commission_rate, rounded to a whole number of cents."

    Design: Difficulty/combinatorial_formula/combinatorial_commission_tier_ordered_dependency_on_total
    """
    # total_premium_cents=527900 (>=500000, <=1000000) -> 0.08; round(527900*0.08)=42232
    ctx = setup_activated_policy(plan_type="RP", aph_yield=180, coverage_level=0.75,
                                 acres=100, share=1, base_premium_rate=0.085)
    comm = ctx["commission"]
    assert comm is not None, "activation must earn a commission for the ELECTED election"
    assert comm["commission_rate"] == 0.08, comm["commission_rate"]
    assert comm["commission_cents"] == 42232, comm["commission_cents"]


def test_commission_tier_below_5000_dollars_uses_tier_1(api):
    """PRD §3.8: "If the total premium is below 500000 cents (five thousand dollars), the
    rate is 0.10 ... The commission_cents is the election's total_premium_cents multiplied
    by the selected commission_rate, rounded to a whole number of cents."

    Design: Difficulty/combinatorial_formula/combinatorial_commission_tier_ordered_dependency_on_total
    """
    # YP, base 0.085: liability 54000c/ac; per_acre=round(54000*0.085*1.00)=4590c;
    #   *100ac = 459000c (<500000) -> tier 0.10; commission=round(459000*0.10)=45900.
    ctx = setup_activated_policy(plan_type="YP", aph_yield=180, coverage_level=0.75,
                                 acres=100, share=1, base_premium_rate=0.085)
    assert ctx["election"]["total_premium_cents"] == 459000, ctx["election"]["total_premium_cents"]
    comm = ctx["commission"]
    assert comm is not None
    assert comm["commission_rate"] == 0.10, comm["commission_rate"]
    assert comm["commission_cents"] == 45900, comm["commission_cents"]


def test_commission_tier_at_exactly_5000_dollars(api):
    """PRD §3.8: "if it is at least 500000 cents and at most 1000000 cents (five thousand
    through ten thousand dollars, inclusive), the rate is 0.08"

    Design: Difficulty/boundary_precision_check/boundary_commission_tier_at_exactly_5000_dollars
    """
    # aph=200, cov=0.50 -> guar 100/ac; liability 100*4*100=40000c/ac;
    #   per_acre=round(40000*0.125*1.00)=5000c; *100ac = 500000c exactly.
    #   500000 is the inclusive lower edge of the 0.08 tier; round(500000*0.08)=40000.
    ctx = setup_activated_policy(plan_type="YP", aph_yield=200, coverage_level=0.50,
                                 acres=100, share=1, base_premium_rate=0.125)
    assert ctx["election"]["total_premium_cents"] == 500000, ctx["election"]["total_premium_cents"]
    comm = ctx["commission"]
    assert comm is not None
    assert comm["commission_rate"] == 0.08, comm["commission_rate"]
    assert comm["commission_cents"] == 40000, comm["commission_cents"]


def test_commission_earned_status_on_activation_at_boundary(api):
    """PRD §3.8: "A commission is created EARNED with clawback_cents at zero."
    PRD §3.2: "for each ELECTED election the system creates or finalizes an AgentCommission
    in EARNED status"

    Design: Difficulty/boundary_precision_check/boundary_commission_tier_at_exactly_5000_dollars
    """
    # Same total_premium_cents == 500000 boundary scenario; assert the commission's
    # lifecycle fields produced by activation.
    ctx = setup_activated_policy(plan_type="YP", aph_yield=200, coverage_level=0.50,
                                 acres=100, share=1, base_premium_rate=0.125)
    assert ctx["election"]["total_premium_cents"] == 500000, ctx["election"]["total_premium_cents"]
    comm = ctx["commission"]
    assert comm is not None
    assert comm["status"] == "EARNED", comm["status"]
    assert comm["clawback_cents"] == 0, comm["clawback_cents"]


def test_commission_tier_3_above_10000_dollars(api):
    """PRD §3.8: "if it is above 1000000 cents (more than ten thousand dollars), the rate
    is 0.06. The commission_cents is the election's total_premium_cents multiplied by the
    selected commission_rate, rounded to a whole number of cents."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_commission_tier_3_above_10000
    """
    # aph=200, cov=0.55 -> guar 110/ac; liability 110*4*100=44000c/ac;
    #   per_acre=round(44000*0.25*1.00)=11000c; *100ac = 1100000c (>1000000) -> 0.06;
    #   round(1100000*0.06)=66000.
    ctx = setup_activated_policy(plan_type="YP", aph_yield=200, coverage_level=0.55,
                                 acres=100, share=1, base_premium_rate=0.25)
    assert ctx["election"]["total_premium_cents"] == 1100000, ctx["election"]["total_premium_cents"]
    comm = ctx["commission"]
    assert comm is not None
    assert comm["commission_rate"] == 0.06, comm["commission_rate"]
    assert comm["commission_cents"] == 66000, comm["commission_cents"]


def test_subsidy_factor_selected_by_coverage_level_85(api):
    """PRD §3.4: "The `subsidy_factor` is looked up by exact `coverage_level` key in the
    federal subsidy table, with no interpolation between levels"
    PRD §3.4: "`0.80` maps to 0.48; and `0.85` maps to 0.38."

    Design: Corner/calculations/subsidy_factor_selected_by_coverage_level_85
    """
    ctx = setup_policy_with_election(plan_type="YP", aph_yield=180, coverage_level=0.85)
    elec = ctx["election"]
    assert elec["subsidy_factor"] == 0.38, elec["subsidy_factor"]


def test_premium_ledger_conserved_subsidy_plus_producer_equals_total(api):
    """PRD §3.4: "The election's producer_premium_cents is then simply the
    total_premium_cents minus the subsidy_cents — derived by subtraction with no
    independent rounding, so that the subsidy share and the producer share always sum
    back exactly to the total."
    PRD §3.4: "The election's subsidy_cents is the total_premium_cents multiplied by the
    subsidy_factor, rounded to a whole number of cents."

    Design: Difficulty/compensating_invariant/invariant_premium_ledger_subsidy_plus_producer_equals_total
    """
    # RP total=527900; cov 0.75 -> factor 0.55; subsidy=round(527900*0.55)=290345;
    #   producer=527900-290345=237555.
    ctx = setup_policy_with_election(plan_type="RP", aph_yield=180, coverage_level=0.75,
                                     base_premium_rate=0.085)
    add_unit(ctx["election"]["id"], ctx["sa_headers"], acres=100, share=1)
    elec = get_success_data(api.get_coverage_election(ctx["election"]["id"], ctx["sa_headers"]))
    assert elec["total_premium_cents"] == 527900, elec["total_premium_cents"]
    assert elec["subsidy_cents"] == 290345, elec["subsidy_cents"]
    assert elec["producer_premium_cents"] == 237555, elec["producer_premium_cents"]
    assert_premium_conserved(elec)


def test_premium_ledger_conserved_at_coverage_level_80(api):
    """PRD §3.4: "The election's producer_premium_cents is then simply the
    total_premium_cents minus the subsidy_cents — derived by subtraction with no
    independent rounding, so that the subsidy share and the producer share always sum back
    exactly to the total."
    PRD §3.4: "`0.80` maps to 0.48"

    Design: Difficulty/compensating_invariant/invariant_premium_ledger_subsidy_plus_producer_equals_total
    """
    # YP cov 0.80 (factor 0.48): guar=144; liability=round(144*4*100)=57600c/ac;
    #   per_acre=round(57600*0.085*1.00)=4896c; *100ac=489600 total.
    #   subsidy=round(489600*0.48)=235008; producer=489600-235008=254592; sum=489600.
    ctx = setup_policy_with_election(plan_type="YP", aph_yield=180, coverage_level=0.80,
                                     base_premium_rate=0.085)
    add_unit(ctx["election"]["id"], ctx["sa_headers"], acres=100, share=1)
    elec = get_success_data(api.get_coverage_election(ctx["election"]["id"], ctx["sa_headers"]))
    assert elec["total_premium_cents"] == 489600, elec["total_premium_cents"]
    assert elec["subsidy_cents"] == 235008, elec["subsidy_cents"]
    assert elec["producer_premium_cents"] == 254592, elec["producer_premium_cents"]
    assert_premium_conserved(elec)


def test_unit_add_recomputes_policy_premium_ledger(api):
    """PRD §3.4: "A policy's total_premium_cents is the sum of total_premium_cents across
    its elections in ELECTED, REPORTED, or INDEMNIFIED status, and its
    producer_premium_cents and subsidy_cents are the corresponding sums of the elections'
    producer and subsidy shares over that same set."

    Design: Corner/endpoints/unit_add_recomputes_election_and_policy_premium_ledger
    """
    ctx = setup_policy_with_election(plan_type="RP", aph_yield=180, coverage_level=0.75,
                                     base_premium_rate=0.085)
    add_unit(ctx["election"]["id"], ctx["sa_headers"], acres=100, share=1)
    policy = get_success_data(api.get_policy(ctx["policy"]["id"], ctx["sa_headers"]))
    assert policy["total_premium_cents"] == 527900, policy["total_premium_cents"]
    assert policy["subsidy_cents"] == 290345, policy["subsidy_cents"]


def test_policy_total_premium_reconciles_to_zero_after_void(api):
    """PRD §3.4: "Voided elections drop out of all three sums, which is precisely why
    voiding and cancellation force a ledger recompute."
    PRD §3.3: "the owning policy's total_premium_cents, producer_premium_cents, and
    subsidy_cents are recomputed with this election excluded"

    Design: Corner/cross_cutting_complexity_layers/derived_field_policy_total_premium_after_void
    """
    ctx = setup_election_with_unit(plan_type="RP", aph_yield=180, coverage_level=0.75,
                                   acres=100, share=1, base_premium_rate=0.085)
    policy = get_success_data(api.get_policy(ctx["policy"]["id"], ctx["sa_headers"]))
    pv = policy["version"]
    api.void_coverage_election(ctx["election"]["id"], {"expected_policy_version": pv},
                               ctx["sa_headers"])
    elec = get_success_data(api.get_coverage_election(ctx["election"]["id"], ctx["sa_headers"]))
    policy_after = get_success_data(api.get_policy(ctx["policy"]["id"], ctx["sa_headers"]))
    assert elec["status"] == "VOID", elec["status"]
    assert policy_after["total_premium_cents"] == 0, policy_after["total_premium_cents"]
