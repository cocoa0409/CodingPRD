"""Case-price calculation tests (PRD §3.5).

Covers the combinatorial case_price formula across channel surcharge, complexity
tier multiplier, and promo discount, plus the LIGHT-tier step-count boundary.
"""
from test_helpers import (
    validate_success,
    setup_submitted_plan,
    api_client, TEST_USERS, make_clinician_headers, get_success_data,
)

BILLING = TEST_USERS["billing_headers"]


def test_case_price_in_office_scan_complex_tier_flat200_discount(api):
    """PRD §3.5: "If the case's `intake_channel` is `IN_OFFICE_SCAN`, add an
    in-office scan surcharge of 25000 cents to the base; an impression-kit case
    adds nothing."
    PRD §3.5: "a count of 29 or more is the COMPLEX tier with a multiplier of
    1.35. Multiply the surcharge-adjusted base by the selected multiplier and
    round that product half-up to whole cents - this rounding happens after the
    multiply and before any discount."
    PRD §3.5: "a `discount_code` of `FLAT200` discounts a flat 20000 cents".

    (500000+25000)*1.35 = 708750 (round), minus 20000 = 688750.

    Design: Difficulty/combinatorial_formula/case_price_mode_a_channel_tier_discount
    """
    ctx = setup_submitted_plan(
        proposed_step_count=30, discount_code="FLAT200",
        intake_channel="IN_OFFICE_SCAN", list_price_cents=500000,
        role_type="ORTHODONTIST",
    )
    approved = validate_success(
        api.approve_plan(ctx["plan"]["id"], ctx["clin_headers"]), 200
    )
    assert approved["status"] == "APPROVED"
    case = validate_success(api.get_case(ctx["case"]["id"], ctx["clin_headers"]), 200)
    assert case["total_contracted_cents"] == 688750, case["total_contracted_cents"]
    assert case["status"] == "PLAN_APPROVED"


def test_case_price_impression_kit_moderate_tier_no_discount(api):
    """PRD §3.5: "an impression-kit case adds nothing."
    PRD §3.5: "a count from 15 through 28 inclusive is the MODERATE tier with a
    multiplier of 1.00".
    PRD §3.5: "any other code, or no code, discounts nothing."

    A second, distinct combinatorial branch (kit + MODERATE + no-discount): the
    700000-list, 20-step case prices to exactly the list price, 700000.

    Design: Difficulty/combinatorial_formula/case_price_mode_a_channel_tier_discount
    """
    ctx = setup_submitted_plan(
        proposed_step_count=20, intake_channel="IMPRESSION_KIT",
        list_price_cents=700000,
    )
    validate_success(api.approve_plan(ctx["plan"]["id"], ctx["clin_headers"]), 200)
    case = validate_success(api.get_case(ctx["case"]["id"], ctx["clin_headers"]), 200)
    assert case["total_contracted_cents"] == 700000, case["total_contracted_cents"]


def test_case_price_light_tier_boundary_step_count_14(api):
    """PRD §3.5: "a count of 14 or fewer is the LIGHT tier with a multiplier of
    0.80".
    PRD §3.5: "Multiply the surcharge-adjusted base by the selected multiplier
    and round that product half-up to whole cents".

    14 steps is the inclusive upper edge of LIGHT: 300000*0.80 = 240000.

    Design: Difficulty/boundary_precision_check/case_price_tier_boundary_step_count_14_light
    """
    ctx = setup_submitted_plan(
        proposed_step_count=14, intake_channel="IMPRESSION_KIT",
        list_price_cents=300000,
    )
    validate_success(api.approve_plan(ctx["plan"]["id"], ctx["clin_headers"]), 200)
    case = validate_success(api.get_case(ctx["case"]["id"], ctx["clin_headers"]), 200)
    assert case["total_contracted_cents"] == 240000, case["total_contracted_cents"]


def test_case_price_moderate_tier_at_step_count_15(api):
    """PRD §3.5: "a count from 15 through 28 inclusive is the MODERATE tier with
    a multiplier of 1.00".

    The step above the LIGHT boundary (15) selects MODERATE: 300000*1.00 = 300000,
    confirming 14 is the inclusive LIGHT edge and 15 crosses into MODERATE.

    Design: Difficulty/boundary_precision_check/case_price_tier_boundary_step_count_14_light
    """
    ctx = setup_submitted_plan(
        proposed_step_count=15, intake_channel="IMPRESSION_KIT",
        list_price_cents=300000,
    )
    validate_success(api.approve_plan(ctx["plan"]["id"], ctx["clin_headers"]), 200)
    case = validate_success(api.get_case(ctx["case"]["id"], ctx["clin_headers"]), 200)
    assert case["total_contracted_cents"] == 300000, case["total_contracted_cents"]


def test_case_price_moderate_tier_no_discount_400000(api):
    """PRD §3.5: "a count from 15 through 28 inclusive is the MODERATE tier with
    a multiplier of 1.00".
    PRD §3.5: "any other code, or no code, discounts nothing."

    IMPRESSION_KIT list 400000, 20 steps MODERATE, no discount -> 400000.

    Design: Corner/calculations/case_price_moderate_tier_no_discount
    """
    ctx = setup_submitted_plan(
        proposed_step_count=20, intake_channel="IMPRESSION_KIT",
        list_price_cents=400000,
    )
    validate_success(api.approve_plan(ctx["plan"]["id"], ctx["clin_headers"]), 200)
    case = validate_success(api.get_case(ctx["case"]["id"], ctx["clin_headers"]), 200)
    assert case["total_contracted_cents"] == 400000, case["total_contracted_cents"]


def test_case_price_welcome15_percentage_discount(api):
    """PRD §3.5: "a `discount_code` of `WELCOME15` discounts 15 percent of the
    tiered total, rounded half-up to whole cents".

    IMPRESSION_KIT list 400000, 20 steps MODERATE -> tiered 400000; discount
    round(400000*0.15)=60000; total 340000.

    Design: Corner/calculations/case_price_welcome15_percentage_discount
    """
    ctx = setup_submitted_plan(
        proposed_step_count=20, intake_channel="IMPRESSION_KIT",
        list_price_cents=400000, discount_code="WELCOME15",
    )
    validate_success(api.approve_plan(ctx["plan"]["id"], ctx["clin_headers"]), 200)
    case = validate_success(api.get_case(ctx["case"]["id"], ctx["clin_headers"]), 200)
    assert case["total_contracted_cents"] == 340000, case["total_contracted_cents"]
