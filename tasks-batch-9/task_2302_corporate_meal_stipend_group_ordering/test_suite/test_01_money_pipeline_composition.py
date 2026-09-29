"""The five-stage placement money pipeline: where each rounding happens."""

from test_helpers import (
    LINES_FOUR_1500,
    LINES_THREE_1000,
    order_line,
    place_order,
    read_period,
    round_half_up,
    setup_drafted_order,
)


def test_three_thousand_cent_lines_tax_to_264_not_263():
    """Per-line rounding before summation is observable on three equal lines.

    PRD §3.5: "Rounding happens once per line, before summation, and this is the
    pinned contract. Applying the rate to the whole subtotal and rounding once at
    the end is *not* the contract and differs observably whenever discarded
    fractions accumulate past half a cent: three lines of 1,000 cents each
    produce 88 plus 88 plus 88, for a `tax_cents` of 264, where a single rounding
    of the 3,000-cent subtotal would have produced 263."

    Design: Difficulty/combinatorial_formula/per_line_tax_rounding_then_sum_yields_264_not_263
    """
    ns = setup_drafted_order(
        order_overrides={"lines": LINES_THREE_1000, "tip_cents": 200}
    )
    order = place_order(ns.order, ns.employee)

    assert order["subtotal_cents"] == 3000
    assert order["tax_cents"] == 264, (
        "tax_cents must be 88 + 88 + 88 = 264, not a single rounding of the "
        f"3,000-cent subtotal (263); got {order['tax_cents']}"
    )
    assert order["tax_cents"] != 263
    assert order["delivery_fee_cents"] == 599
    assert order["service_fee_cents"] == 300
    assert order["covered_base_cents"] == 4163
    assert order["gross_total_cents"] == 4363


def test_two_thousand_cent_lines_tax_to_176_where_one_rounding_would_give_175():
    """Two 1,000-cent lines round to 88 each; the aggregate would round to 175.

    PRD §3.5: "`tax_cents` is computed differently: for each line, multiply that
    line's base by the sales tax rate of 8.75 percent, round the product half-up
    to a whole cent, and add the rounded figure to a running total."

    Design: Difficulty/combinatorial_formula/per_line_tax_rounding_then_sum_yields_264_not_263
    """
    lines = [order_line("Pad Thai", 1000, 1), order_line("Green Curry", 1000, 1)]
    ns = setup_drafted_order(order_overrides={"lines": lines})
    order = place_order(ns.order, ns.employee)

    assert order["subtotal_cents"] == 2000
    assert round_half_up(2000 * 0.0875) == 175, "the aggregate rounding is 175"
    assert order["tax_cents"] == 176, (
        f"88 + 88 = 176 is the pinned contract, got {order['tax_cents']}"
    )
    assert order["tax_cents"] != 175


def test_service_fee_clamp_then_tier_discount_yields_450_not_500():
    """The 500-cent clamp is applied before the 10 percent volume discount.

    PRD §3.5: "Clamp-then-discount is the contract and discount-then-clamp is
    observably wrong: with a subtotal of 6,000 and tax of 524, the raw fee is
    600, the clamped fee is 500, the tier rate is 10 percent, and the service fee
    is 500 minus 50, which is 450 — whereas discounting first would give 540 and
    then clamp back up to 500."

    Design: Difficulty/combinatorial_formula/service_fee_clamp_then_tier_discount_yields_450_not_500
    """
    ns = setup_drafted_order(order_overrides={"lines": LINES_FOUR_1500})
    order = place_order(ns.order, ns.employee)

    assert order["subtotal_cents"] == 6000
    assert order["tax_cents"] == 524, "four 1,500-cent lines tax to 131 each"
    assert order["delivery_fee_cents"] == 0, "6,000 clears the 3,500 threshold"
    assert order["service_fee_cents"] == 450, (
        f"clamped 500 less a 10 percent discount of 50, got {order['service_fee_cents']}"
    )
    assert order["service_fee_cents"] != 500, "the discount must be applied"
    assert order["service_fee_cents"] != 540, "the discount must follow the clamp"
    assert order["covered_base_cents"] == 6974
    assert order["employer_covered_cents"] == 2500
    assert order["employee_card_cents"] == 4474


def test_service_fee_clamp_then_twenty_five_percent_tier_yields_375():
    """At the 12,000-cent tier the clamped 500 loses 125, never 900 re-clamped.

    PRD §3.5: "Stage 2c applies a volume discount whose tier is selected from the
    pre-fee base, meaning `subtotal_cents` plus `tax_cents`: a pre-fee base of at
    least 12,000 cents earns a 25 percent discount, a pre-fee base of at least
    5,000 cents but below 12,000 earns a 10 percent discount, and anything below
    5,000 earns no discount."

    Design: Difficulty/combinatorial_formula/service_fee_clamp_then_tier_discount_yields_450_not_500
    """
    lines = [order_line(f"Platter {index}", 3000, 1) for index in range(4)]
    ns = setup_drafted_order(order_overrides={"lines": lines})
    order = place_order(ns.order, ns.employee)

    assert order["subtotal_cents"] == 12000
    assert order["tax_cents"] == 1052, "3,000 cents taxes to 263 per line"
    assert order["service_fee_cents"] == 375, (
        f"clamped 500 less a 25 percent discount of 125, got {order['service_fee_cents']}"
    )
    assert order["service_fee_cents"] != 900, (
        "discounting the raw 1,200 first and clamping afterwards is not the contract"
    )
    assert order["covered_base_cents"] == 13427


def test_employer_split_nested_min_with_employer_tip_branch_yields_1987():
    """The employer share is the smallest of covered base, cap and availability.

    PRD §3.5: "`employer_covered_cents` is the smallest of three independent
    ceilings: the covered base itself, the pinned rule's `per_meal_cap_cents`, and
    the period's `available_cents`."

    Design: Difficulty/combinatorial_formula/employer_split_nested_min_with_employer_tip_branch_yields_1987
    """
    ns = setup_drafted_order(
        group_overrides={"name": "Contractors", "headcount_planned": 1},
        rule_overrides={
            "per_meal_cap_cents": 2500,
            "daily_meal_limit": 2,
            "monthly_allocation_cents": 2000,
            "tip_coverage_policy": "EMPLOYER_COVERS_TIP",
        },
        employee_overrides={"full_name": "Cleo Chen", "email": "cleo@acme.test"},
        order_overrides={"tip_cents": 200},
    )
    order = place_order(ns.order, ns.employee)

    assert order["subtotal_cents"] == 1000
    assert order["tax_cents"] == 88
    assert order["delivery_fee_cents"] == 599
    assert order["service_fee_cents"] == 100
    assert order["tip_covered_by_employer_cents"] == 200
    assert order["covered_base_cents"] == 1987
    assert order["employer_covered_cents"] == 1987, (
        "the covered base is smaller than both the 2,500 cap and the 2,000 "
        f"allocation, got {order['employer_covered_cents']}"
    )
    assert order["employee_card_cents"] == 0
    assert order["gross_total_cents"] == 1987
    assert order["admin_fee_cents"] == 99, (
        "1,987 at 5 percent is 99.35, which rounds half-up to 99"
    )

    period = read_period(ns.period["id"])
    assert period["reserved_cents"] == 1987
    assert period["available_cents"] == 13


def test_employee_pays_tip_branch_keeps_the_tip_out_of_the_covered_base():
    """The tip branch changes the covered base and the administration fee.

    PRD §3.5: "`tip_covered_by_employer_cents` is equal to `tip_cents` when the
    pinned rule's `tip_coverage_policy` is `EMPLOYER_COVERS_TIP`, and 0 when it is
    `EMPLOYEE_PAYS_TIP`."

    Design: Difficulty/combinatorial_formula/employer_split_nested_min_with_employer_tip_branch_yields_1987
    """
    ns = setup_drafted_order(
        group_overrides={"name": "Contractors", "headcount_planned": 1},
        rule_overrides={
            "per_meal_cap_cents": 2500,
            "daily_meal_limit": 2,
            "monthly_allocation_cents": 2000,
            "tip_coverage_policy": "EMPLOYEE_PAYS_TIP",
        },
        employee_overrides={"full_name": "Cleo Chen", "email": "cleo@acme.test"},
        order_overrides={"tip_cents": 200},
    )
    order = place_order(ns.order, ns.employee)

    assert order["tip_covered_by_employer_cents"] == 0
    assert order["covered_base_cents"] == 1787, "the 200-cent tip stays outside"
    assert order["employer_covered_cents"] == 1787
    assert order["employee_card_cents"] == 200, "the uncovered tip lands on the card"
    assert order["gross_total_cents"] == 1987, "the customer-facing total is unchanged"
    assert order["admin_fee_cents"] == 89, (
        "1,787 at 5 percent is 89.35, which rounds half-up to 89"
    )
