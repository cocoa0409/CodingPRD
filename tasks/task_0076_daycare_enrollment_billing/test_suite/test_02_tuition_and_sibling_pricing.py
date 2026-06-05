"""Tuition pricing: sliding-scale tier selection, pinned per-step rounding,
the sibling-discount cascade, and the single-anchor invariant.

Translates queue-A difficulty instances (combinatorial_formula, dual_variant
tuition side, transitive_cascade activate, compensating_invariant sibling) and
queue-B corner instances (cross_cutting derived tier recompute).
"""
from test_helpers import (
    validate_success, validate_paginated, get_success_data,
    make_director_headers, make_billing_headers,
)
import test_helpers.fixtures as fx

DIRECTOR = make_director_headers()
BILLING = make_billing_headers()


def test_sliding_scale_tier_selection_inclusive_bound(api):
    """PRD §3.2: "the one-person poverty line of 15,080,000 cents plus 5,320,000
    cents for each additional household member beyond the first."
    PRD §3.2: "the first row whose max_fpl_ratio_pct is greater than or equal to
    the family's floored ratio wins, and its tier becomes the family's
    sliding_scale_tier."

    income 1,960,400, size 1: ratio = floor(1960400*100/15080000) = 13; the
    lowest-bounded row whose max_fpl_ratio_pct (130) >= 13 wins -> TIER_A.

    Design: Difficulty/combinatorial_formula/sliding_scale_tier_selection_threshold_and_fpl_interaction
    """
    center = fx.create_center(cacfp_tier="TIER_I")
    fx.add_sliding_scale_row(center["id"], "TIER_A", 130, 40)
    fx.add_sliding_scale_row(center["id"], "TIER_B", 185, 70)
    fx.add_full_pay_scale(center["id"])
    resp = api.create_family(
        {"center_id": center["id"], "primary_contact_name": "P",
         "annual_household_income_cents": 1960400, "household_size": 1}, DIRECTOR)
    data = validate_success(resp, 201)
    assert data["sliding_scale_tier"] == "TIER_A"


def test_sliding_scale_full_pay_catch_all(api):
    """PRD §3.2: "Because the FULL_PAY row carries the sentinel bound of 999999,
    it always serves as the guaranteed catch-all when no lower-bounded tier
    qualifies."

    High income (50,000,000, size 2): poverty base = 15,080,000 + 5,320,000 =
    20,400,000; ratio = floor(5000000000/20400000) = 245, far exceeds TIER_A
    (130) and TIER_B (185) bounds -> FULL_PAY catch-all.

    Design: Difficulty/combinatorial_formula/sliding_scale_tier_selection_threshold_and_fpl_interaction
    """
    center = fx.create_center(cacfp_tier="TIER_I")
    fx.add_sliding_scale_row(center["id"], "TIER_A", 130, 40)
    fx.add_sliding_scale_row(center["id"], "TIER_B", 185, 70)
    fx.add_full_pay_scale(center["id"])
    resp = api.create_family(
        {"center_id": center["id"], "primary_contact_name": "P",
         "annual_household_income_cents": 50000000, "household_size": 2}, DIRECTOR)
    data = validate_success(resp, 201)
    assert data["sliding_scale_tier"] == "FULL_PAY"


def test_tuition_tier_b_anchor_no_sibling(api):
    """PRD §3.5: "the post-subsidy amount is the locked base tuition multiplied by
    the locked parent-share percentage divided by 100, rounded half up to a whole
    cent. The net tuition is then that post-subsidy amount multiplied by the
    quantity (100 minus the enrollment's sibling_discount_pct) divided by 100".
    PRD §3.5: "the earliest-created active enrollment is the anchor and carries a
    sibling_discount_pct of 0".

    income 5,000,000 size 4 with TIER_B(185)+FULL_PAY rows -> ratio 16 -> TIER_B
    (parent_share 70); base 120000 -> round(120000*0.70)=84000, anchor 0% -> 84000.

    Design: Difficulty/dual_variant_calc/tuition_pricing_vs_cacfp_distinct_entity_domains
    """
    center = fx.create_center(cacfp_tier="TIER_I")
    fx.add_sliding_scale_row(center["id"], "TIER_B", 185, 70)
    fx.add_full_pay_scale(center["id"])
    classroom = fx.create_classroom(
        center["id"], base_monthly_tuition_cents=120000)
    family = fx.create_family(
        center["id"], annual_household_income_cents=5000000, household_size=4)
    fam = get_success_data(api.get_family(family["id"], DIRECTOR))
    assert fam["sliding_scale_tier"] == "TIER_B"
    child, enr = fx.create_active_enrollment(classroom, family)
    enr = get_success_data(api.get_enrollment(enr["id"], DIRECTOR))
    assert enr["monthly_net_tuition_cents"] == 84000


def test_tier_b_family_sliding_scale_tier_assigned(api):
    """PRD §3.2: "the first row whose max_fpl_ratio_pct is greater than or equal to
    the family's floored ratio wins, and its tier becomes the family's
    sliding_scale_tier."

    income 5,000,000 size 4: fpl_base = 15,080,000 + 3*5,320,000 = 31,040,000;
    ratio = floor(500000000/31040000) = 16. With only TIER_B (185) and FULL_PAY
    rows present, the lowest bound >= 16 is TIER_B (185) -> sliding_scale_tier
    TIER_B (parent_share 70).

    Design: Difficulty/dual_variant_calc/tuition_pricing_vs_cacfp_distinct_entity_domains
    """
    center = fx.create_center(cacfp_tier="TIER_I")
    fx.add_sliding_scale_row(center["id"], "TIER_B", 185, 70)
    fx.add_full_pay_scale(center["id"])
    resp = api.create_family(
        {"center_id": center["id"], "primary_contact_name": "P",
         "annual_household_income_cents": 5000000, "household_size": 4}, DIRECTOR)
    data = validate_success(resp, 201)
    assert data["sliding_scale_tier"] == "TIER_B"


def test_tuition_pinned_round_order_scale_then_sibling(api):
    """PRD §3.5: "the sliding scale is applied first, and the sibling discount is
    applied to that result. ... Rounding happens at each of the two steps; the
    system does not defer rounding to a single final step."

    base 99999, parent_share 70: round(99999*0.70)=69999 (anchor); junior:
    round(69999*0.90)=62999.

    Design: Difficulty/combinatorial_formula/monthly_net_tuition_pinned_round_order_scale_then_sibling
    """
    (center, classroom, family, elder, elder_enr,
     younger, younger_enr) = fx.setup_two_active_siblings(base_tuition_cents=99999)
    elder_enr = get_success_data(api.get_enrollment(elder_enr["id"], DIRECTOR))
    younger_enr = get_success_data(api.get_enrollment(younger_enr["id"], DIRECTOR))
    assert elder_enr["monthly_net_tuition_cents"] == 69999
    assert younger_enr["monthly_net_tuition_cents"] == 62999
    assert younger_enr["sibling_discount_pct"] == 10


def test_junior_sibling_carries_ten_percent_discount(api):
    """PRD §3.5: "every junior active sibling carries the sibling discount of 10
    percent."
    PRD §3.5: "The invariant is that a family with at least one active sibling has
    exactly one anchor at 0 percent."

    Design: Difficulty/combinatorial_formula/monthly_net_tuition_pinned_round_order_scale_then_sibling
    """
    (center, classroom, family, elder, elder_enr,
     younger, younger_enr) = fx.setup_two_active_siblings(base_tuition_cents=99999)
    elder_enr = get_success_data(api.get_enrollment(elder_enr["id"], DIRECTOR))
    younger_enr = get_success_data(api.get_enrollment(younger_enr["id"], DIRECTOR))
    assert elder_enr["sibling_discount_pct"] == 0
    assert younger_enr["sibling_discount_pct"] == 10


def test_activate_cascade_capacity_sibling_rerank_tuition(api):
    """PRD §3.4: "the classroom's active_enrollment_count is incremented by one and
    its status recomputed".
    PRD §2.9: "FULL once the active count reaches the licensed capacity."
    PRD §3.5: "the system re-ranks all of the family's active siblings by
    enrollment creation time, assigns the anchor 0 percent and each junior sibling
    the 10-percent discount, and recomputes monthly_net_tuition_cents for every
    affected enrollment."

    Design: Difficulty/transitive_cascade/activate_cascade_capacity_sibling_rerank_tuition_depth3
    """
    (center, classroom, family, elder, elder_enr,
     younger, younger_enr) = fx.setup_two_active_siblings(
        base_tuition_cents=99999, capacity=2)
    younger_enr = get_success_data(api.get_enrollment(younger_enr["id"], DIRECTOR))
    room = get_success_data(api.get_classroom(classroom["id"], DIRECTOR))
    assert younger_enr["monthly_net_tuition_cents"] == 62999
    assert younger_enr["sibling_discount_pct"] == 10
    assert room["active_enrollment_count"] == 2
    assert room["status"] == "FULL"


def test_activate_increments_count_and_keeps_open_below_capacity(api):
    """PRD §3.4: "the classroom's active_enrollment_count is incremented by one and
    its status recomputed".
    PRD §2.9: "a classroom is OPEN while its active count is below its licensed
    capacity".

    Design: Difficulty/transitive_cascade/activate_cascade_capacity_sibling_rerank_tuition_depth3
    """
    center, classroom, family, child, enr = fx.setup_single_active_enrollment(
        classroom_overrides={"licensed_capacity": 5})
    room = get_success_data(api.get_classroom(classroom["id"], DIRECTOR))
    assert room["active_enrollment_count"] == 1
    assert room["status"] == "OPEN"


def test_withdraw_elder_reanchors_younger_to_zero(api):
    """PRD §3.5: "When an active sibling withdraws or graduates, the same cascade
    runs across the family's remaining active siblings — and because the eldest may
    have departed, a junior sibling can become the new anchor and drop to 0 percent
    — with each affected enrollment's net tuition recomputed."

    elder (anchor) withdrawn -> younger becomes anchor 0%, net 62999->69999.

    Design: Difficulty/compensating_invariant/withdraw_sibling_conserves_single_anchor_invariant
    """
    (center, classroom, family, elder, elder_enr,
     younger, younger_enr) = fx.setup_two_active_siblings(base_tuition_cents=99999)
    resp = api.withdraw_enrollment(elder_enr["id"], DIRECTOR)
    withdrawn = validate_success(resp, 200)
    assert withdrawn["status"] == "WITHDRAWN"
    younger_enr = get_success_data(api.get_enrollment(younger_enr["id"], DIRECTOR))
    assert younger_enr["sibling_discount_pct"] == 0
    assert younger_enr["monthly_net_tuition_cents"] == 69999


def test_single_anchor_invariant_preserved_after_withdraw(api):
    """PRD §3.5: "The invariant is that a family with at least one active sibling
    has exactly one anchor at 0 percent."
    PRD §3.5: "This compensating recomputation conserves the one-anchor invariant
    after every departure."

    Design: Difficulty/compensating_invariant/withdraw_sibling_conserves_single_anchor_invariant
    """
    (center, classroom, family, elder, elder_enr,
     younger, younger_enr) = fx.setup_two_active_siblings(base_tuition_cents=99999)
    get_success_data(api.withdraw_enrollment(elder_enr["id"], DIRECTOR))
    enrs, _ = validate_paginated(
        api.list_enrollments(DIRECTOR, params={"classroom_id": classroom["id"]}))
    active = [e for e in enrs if e["status"] == "ACTIVE"]
    anchors = [e for e in active if e["sibling_discount_pct"] == 0]
    assert len(anchors) == 1, f"exactly one anchor expected, got {len(anchors)}"


def test_patch_family_recomputes_sliding_scale_tier(api):
    """PRD §3.2: "Either change recomputes the family's sliding_scale_tier from the
    same table and increments the family's version."

    income raised from a TIER_A level to a FULL_PAY level -> tier flips.

    Design: Corner/cross_cutting_complexity_layers/derived_sliding_scale_tier_recomputed_on_patch
    """
    center = fx.create_center(cacfp_tier="TIER_I")
    fx.add_sliding_scale_row(center["id"], "TIER_A", 130, 40)
    fx.add_full_pay_scale(center["id"])
    family = get_success_data(api.create_family(
        {"center_id": center["id"], "primary_contact_name": "P",
         "annual_household_income_cents": 1960400, "household_size": 1}, DIRECTOR))
    assert family["sliding_scale_tier"] == "TIER_A"
    resp = api.patch_family(
        family["id"], {"annual_household_income_cents": 50000000}, BILLING)
    data = validate_success(resp, 200)
    assert data["sliding_scale_tier"] == "FULL_PAY"
