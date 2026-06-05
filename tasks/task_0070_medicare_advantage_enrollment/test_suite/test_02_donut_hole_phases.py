"""Donut-hole drug-phase cost-share computation on POST .../claims.

Covers the per-segment phase split, round-per-segment-then-sum ordering, the
ICL initial->gap boundary, and accumulator advancement.
"""
from test_helpers import (
    validate_success, set_clock, setup_active_part_d, setup_active_part_d_with_total,
    post_claim, create_drug_claim_payload, api_client, TEST_USERS,
)

ADMIN = TEST_USERS["enrollment_admin_headers"]


def test_claim_straddles_deductible_and_initial_phases(api):
    """PRD §3.8: "DEDUCTIBLE phase, while T is below 54,500 cents: the member pays
    100% of the segment."
    PRD §3.8: "INITIAL phase, while T is at least 54,500 cents and below 503,000 cents:
    the member pays 25% of the segment."
    PRD §3.8: "A claim's phase_at_post records the phase of its very first cent."
    PRD §3.8: "After a claim posts, T is advanced by the claim's full list_price_cents
    and O is advanced by the claim's member_share_cents"

    Design: Difficulty/combinatorial_formula/donut_hole_claim_straddles_deductible_and_initial_phases
    """
    set_clock("2024-11-01T00:00:00.000Z")
    _ben, _iep, _pdp, pde = setup_active_part_d()
    res = api.post_drug_claim(pde["id"],
                              create_drug_claim_payload(60000, "2024-11-05T00:00:00.000Z"), ADMIN)
    claim = validate_success(res, 201)
    # 54500 at 100% (deductible) + 5500 at 25% = round_half_up(1375.0)=1375 -> 55875.
    assert claim["member_share_cents"] == 55875
    assert claim["phase_at_post"] == "DEDUCTIBLE"

    enr = validate_success(api.get_part_d_enrollment(pde["id"], ADMIN), 200)
    assert enr["total_drug_cost_cents"] == 60000
    assert enr["member_oop_cents"] == 55875


def test_round_per_segment_then_sum_ordering(api):
    """PRD §3.8: "For each segment that carries a 25% coinsurance (the initial and gap
    phases), the member share for that segment is the segment's cents multiplied by 25%,
    rounded half up to whole cents."
    PRD §3.8: "The claim's member_share_cents is the sum of the per-segment member
    shares - each segment rounded first, then the rounded segment shares summed
    (round-per-segment-then-sum, not sum-then-round)."

    Design: Difficulty/combinatorial_formula/donut_hole_round_per_segment_then_sum_ordering
    """
    set_clock("2024-11-01T00:00:00.000Z")
    _ben, _iep, _pdp, pde = setup_active_part_d()
    # Seed exactly through the deductible: 54500 list all in 100% deductible -> T=54500.
    post_claim(pde["id"], 54500, "2024-11-05T00:00:00.000Z")
    # Two 333c claims in INITIAL: each round_half_up(83.25)=83.
    c1 = validate_success(api.post_drug_claim(
        pde["id"], create_drug_claim_payload(333, "2024-11-06T00:00:00.000Z"), ADMIN), 201)
    c2 = validate_success(api.post_drug_claim(
        pde["id"], create_drug_claim_payload(333, "2024-11-07T00:00:00.000Z"), ADMIN), 201)
    assert c1["member_share_cents"] == 83
    assert c2["member_share_cents"] == 83

    enr = validate_success(api.get_part_d_enrollment(pde["id"], ADMIN), 200)
    # oop = 54500 (deductible seed) + 83 + 83 = 54666.
    assert enr["member_oop_cents"] == 54666


def test_icl_boundary_initial_to_gap_crossing(api):
    """PRD §3.8: "GAP phase, while T is at least 503,000 cents and O is below 800,000
    cents: the member pays 25% of the segment."
    PRD §3.8: "the initial-to-gap crossing occurs when T reaches 503,000 cents (at or
    above)"
    PRD §3.8: "A claim's phase_at_post records the phase of its very first cent."

    Design: Difficulty/boundary_precision_check/donut_hole_icl_boundary_initial_to_gap_crossing
    """
    set_clock("2024-11-01T00:00:00.000Z")
    # Drive T to exactly 503000 via a seeding claim, then post one 1000c claim.
    _ben, pde = setup_active_part_d_with_total(503000)
    assert pde["total_drug_cost_cents"] == 503000
    res = api.post_drug_claim(pde["id"],
                              create_drug_claim_payload(1000, "2024-11-06T00:00:00.000Z"), ADMIN)
    claim = validate_success(res, 201)
    # First cent at T=503000 >= ICL -> GAP. 1000 * 25% = 250.
    assert claim["phase_at_post"] == "GAP"
    assert claim["member_share_cents"] == 250


def test_claim_advances_accumulators_in_initial_phase(api):
    """PRD §3.8: "INITIAL phase, while T is at least 54,500 cents and below 503,000
    cents: the member pays 25% of the segment."
    PRD §3.8: "After a claim posts, T is advanced by the claim's full list_price_cents
    and O is advanced by the claim's member_share_cents"

    Design: Corner/endpoints/post_drug_claims_advances_accumulators_side_effect
    """
    set_clock("2024-11-01T00:00:00.000Z")
    _ben, _iep, _pdp, pde = setup_active_part_d()
    # Prior 60000c claim: total 60000, oop 55875 (past the 54500 deductible).
    post_claim(pde["id"], 60000, "2024-11-05T00:00:00.000Z")
    res = api.post_drug_claim(pde["id"],
                              create_drug_claim_payload(100000, "2024-11-06T00:00:00.000Z"), ADMIN)
    claim = validate_success(res, 201)
    # Entirely in INITIAL (T 60000 -> 160000, < 503000): 100000 * 25% = 25000.
    assert claim["member_share_cents"] == 25000
    assert claim["phase_at_post"] == "INITIAL"

    enr = validate_success(api.get_part_d_enrollment(pde["id"], ADMIN), 200)
    assert enr["total_drug_cost_cents"] == 160000
    assert enr["member_oop_cents"] == 80875
