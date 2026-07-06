"""Acrylic-system pricing: marginal area tiering, add-on flat pricing, and the
per-line-item promo discount rounding order.

Queue A (difficulty): combinatorial_formula (tiered system price, per-line discount).
Queue B (corner): calculations / system_price_tier_boundary_above_80.
"""
from test_helpers import (
    setup_design_complete_project, create_quote_on,
)


def test_tiered_system_price_three_tiers(api):
    """PRD §3.3: "The snapshot area is split across two breakpoints at 40 and 80
    square feet: the first 40 square feet are billed at the full base rate; the
    portion above 40 square feet and up to and including 80 square feet — the next
    40 square feet — is billed at 90% of the base rate; and any area strictly
    beyond 80 square feet is billed at 80% of the base rate."
    PRD §3.3: "3750 cents per square foot for SMOOTH_ACRYLIC, 5900 for
    TILE_LOOK_ACRYLIC, and 8250 for STONE_LOOK_ACRYLIC."

    Design: Difficulty/combinatorial_formula/tiered_system_price_three_tiers_mode_a
    """
    ctx = setup_design_complete_project(api, area=100.0)
    quote = create_quote_on(api, ctx, wall_system="TILE_LOOK_ACRYLIC", color="WHITE")
    assert quote["system_price_cents"] == 542800, (
        f"TILE/100 tiered price must be 542800, got {quote['system_price_cents']}"
    )


def test_tiered_price_flows_to_net_with_no_addon_or_promo(api):
    """PRD §3.3: "The net price (net_price_cents) is the system price plus the
    add-on price minus the discount."
    PRD §3.3: "The add-on price (addon_price_cents) is a flat amount fixed by the
    accessibility add-on: 0 cents for NONE, 29900 cents for GRAB_BARS, 249900
    cents for BARRIER_FREE_SHOWER, and 449900 cents for WALK_IN_TUB."

    Design: Difficulty/combinatorial_formula/tiered_system_price_three_tiers_mode_a
    """
    ctx = setup_design_complete_project(api, area=100.0)
    quote = create_quote_on(api, ctx, wall_system="TILE_LOOK_ACRYLIC", color="WHITE")
    assert quote["addon_price_cents"] == 0
    assert quote["discount_cents"] == 0
    assert quote["net_price_cents"] == 542800, (
        f"net must equal system+addon-discount = 542800, got {quote['net_price_cents']}"
    )


def test_per_line_promo_discount_rounding(api):
    """PRD §3.3: "when SPRING750 is present, the system-price line and the
    add-on-price line are each multiplied by 7.5% and each rounded half-up to a
    whole cent independently, and only then are the two rounded line discounts
    summed to give the total discount; when no recognized code is present, the
    discount is 0."

    Design: Difficulty/combinatorial_formula/per_line_rounding_discount_mode_b
    """
    ctx = setup_design_complete_project(api, area=60.0)
    quote = create_quote_on(api, ctx, wall_system="SMOOTH_ACRYLIC", color="WHITE",
                            accessibility_addon="WALK_IN_TUB", promo_code="SPRING750")
    assert quote["system_price_cents"] == 217500
    assert quote["addon_price_cents"] == 449900
    # round(217500*0.075)=16313 ; round(449900*0.075)=33743 ; sum = 50056
    assert quote["discount_cents"] == 50056, (
        f"per-line rounded discount must be 50056, got {quote['discount_cents']}"
    )


def test_per_line_discount_flows_to_net(api):
    """PRD §3.3: "The net price (net_price_cents) is the system price plus the
    add-on price minus the discount."

    Design: Difficulty/combinatorial_formula/per_line_rounding_discount_mode_b
    """
    ctx = setup_design_complete_project(api, area=60.0)
    quote = create_quote_on(api, ctx, wall_system="SMOOTH_ACRYLIC", color="WHITE",
                            accessibility_addon="WALK_IN_TUB", promo_code="SPRING750")
    # 217500 + 449900 - 50056 = 617344
    assert quote["net_price_cents"] == 617344, (
        f"net must be 617344, got {quote['net_price_cents']}"
    )


def test_system_price_crosses_80_sqft_breakpoint(api):
    """PRD §3.3: "The snapshot area is split across two breakpoints at 40 and 80
    square feet: the first 40 square feet are billed at the full base rate; the
    portion above 40 square feet and up to and including 80 square feet — the next
    40 square feet — is billed at 90% of the base rate; and any area strictly
    beyond 80 square feet is billed at 80% of the base rate."

    Design: Corner/calculations/system_price_tier_boundary_above_80
    """
    ctx = setup_design_complete_project(api, area=81.0)
    quote = create_quote_on(api, ctx, wall_system="TILE_LOOK_ACRYLIC", color="WHITE")
    # 40*5900 + 40*5900*0.9 + 1*5900*0.8 = 236000 + 212400 + 4720 = 453120
    assert quote["system_price_cents"] == 453120, (
        f"TILE/81 must be 453120 (one sqft in the third tier), got {quote['system_price_cents']}"
    )
