"""Dual-variant calculations: the two profitability variants on a matter and
the two credited-collection variants behind a partner's formula scores."""

from test_helpers import (
    allocate_origination_credit,
    approx2,
    approx4,
    approx6,
    create_credit_arbiter,
    read_cycle,
    read_partner,
    setup_formula_matter,
)


def test_profitability_variants_diverge_by_the_overhead_charge(api):
    """PRD 3.2: "Under the fully-loaded variant, the same numerator is reduced
    further by an overhead charge of 9,000 cents — 90 dollars — for each of the
    matter's `verified_billable_hours`, giving `profitability_index_fully_loaded`
    as `collected_cents` less `direct_cost_cents` less that overhead amount,
    divided by `collected_cents`, again rounded half up to 4 decimal places."

    Design: Difficulty/dual_variant_calc/matter_profitability_contribution_vs_fully_loaded_diverge
    """
    scenario = setup_formula_matter(
        api,
        billed_delta_cents=10_000_000,
        collected_delta_cents=8_500_000,
        direct_cost_delta_cents=1_000_000,
        verified_hours=200.00,
    )
    matter = scenario["matter"]

    assert matter["realization_pct"] == approx4(0.8500)
    assert matter["verified_billable_hours"] == approx2(200.00)
    assert matter["profitability_index_contribution"] == approx4(0.8824)
    assert matter["profitability_index_fully_loaded"] == approx4(0.6706)
    assert matter["profitability_index_contribution"] != matter["profitability_index_fully_loaded"]
    delta = matter["profitability_index_contribution"] - matter["profitability_index_fully_loaded"]
    assert delta == approx4(0.2118)


def test_profitability_variants_coincide_without_verified_hours(api):
    """PRD 3.2: "Both indices are 0.0000 whenever `collected_cents` is 0, even
    when direct costs have been posted; both may legitimately be negative and
    neither is floored at zero; and when a matter has no verified billable hours
    the two variants are numerically identical."

    Design: Difficulty/dual_variant_calc/matter_profitability_contribution_vs_fully_loaded_diverge
    """
    scenario = setup_formula_matter(
        api,
        billed_delta_cents=10_000_000,
        collected_delta_cents=8_500_000,
        direct_cost_delta_cents=1_000_000,
        verified_hours=None,
    )
    matter = scenario["matter"]

    assert matter["verified_billable_hours"] == approx2(0.00)
    assert matter["profitability_index_contribution"] == approx4(0.8824)
    assert matter["profitability_index_fully_loaded"] == approx4(0.8824)
    assert matter["profitability_index_contribution"] == matter["profitability_index_fully_loaded"]


def test_formula_score_variants_diverge_while_the_matter_stays_open(api):
    """PRD 3.5: "Under the **final collected** variant, each matter's basis is
    simply its `collected_cents` and the matter scope is matters in `CLOSED`
    only, so an open matter contributes nothing however much has been collected
    on it."

    Design: Difficulty/dual_variant_calc/partner_formula_score_provisional_vs_final_diverge
    """
    scenario = setup_formula_matter(
        api,
        billed_delta_cents=10_000_000,
        collected_delta_cents=8_500_000,
        direct_cost_delta_cents=1_000_000,
        verified_hours=200.00,
    )
    arbiter = create_credit_arbiter(api, full_name="Rex Arbiter", practice_group="REGULATORY")
    allocate_origination_credit(
        api,
        cycle_id=scenario["cycle"]["id"],
        matter_id=scenario["matter"]["id"],
        claimant_id=scenario["partner"]["id"],
        arbiter_id=arbiter["id"],
        approved_pct=100.00,
    )

    partner = read_partner(api, scenario["partner"]["id"])
    assert partner["credited_collection_provisional_cents"] == 8_500_000
    assert partner["credited_collection_final_cents"] == 0
    assert partner["normalized_credit_index_provisional"] == approx6(1.000000)
    assert partner["normalized_credit_index_final"] == approx6(0.000000)
    assert partner["blended_realization_pct"] == approx4(0.8500)
    assert partner["weighted_profitability_points"] == approx4(0.6706)
    assert partner["formula_score_provisional"] == approx4(60.6342)
    assert partner["formula_score_final"] == approx4(1.6667)
    assert partner["formula_score_provisional"] != partner["formula_score_final"]


def test_cycle_total_consumes_the_provisional_variant_before_true_up(api):
    """PRD 3.5: "The result is stored as `formula_score_provisional` and is the
    figure consumed while the cycle sits in `OPEN_INTAKE`, `SELF_ASSESSMENT`,
    `PEER_REVIEW`, `DELIBERATION` or `AWARDS_PUBLISHED`."

    Design: Difficulty/dual_variant_calc/partner_formula_score_provisional_vs_final_diverge
    """
    scenario = setup_formula_matter(
        api,
        billed_delta_cents=10_000_000,
        collected_delta_cents=8_500_000,
        direct_cost_delta_cents=1_000_000,
        verified_hours=200.00,
    )
    arbiter = create_credit_arbiter(api, full_name="Rex Arbiter", practice_group="REGULATORY")
    allocate_origination_credit(
        api,
        cycle_id=scenario["cycle"]["id"],
        matter_id=scenario["matter"]["id"],
        claimant_id=scenario["partner"]["id"],
        arbiter_id=arbiter["id"],
        approved_pct=100.00,
    )

    cycle = read_cycle(api, scenario["cycle"]["id"])
    partner = read_partner(api, scenario["partner"]["id"])
    assert cycle["state"] == "OPEN_INTAKE"
    assert cycle["total_formula_score"] == approx4(60.6342)
    assert cycle["total_formula_score"] == approx4(partner["formula_score_provisional"])
