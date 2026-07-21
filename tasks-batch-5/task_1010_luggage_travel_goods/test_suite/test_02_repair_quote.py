"""Repair quoting: dual-variant cost, nested labor clamp, and the empty-line-set guard."""
import test_helpers as H

# Two RepairLines used by the dual-variant instance.
DUAL_LINES = [
    {"repair_type": "WHEEL", "labor_hours": 2, "complexity": "STANDARD", "parts_cost_cents": 4000},
    {"repair_type": "ZIPPER", "labor_hours": 1.5, "complexity": "COMPLEX", "parts_cost_cents": 1500},
]


# ==========================================================================
# Queue A — dual-variant calc: customer-pay vs warranty-covered
# ==========================================================================
def test_repair_quote_customer_pay_adds_diagnostic_fee(api):
    """PRD §3.4: "For a `CUSTOMER_PAY` order, `quoted_total_cents` is the lines total plus a
    diagnostic fee of 2500 cents, and `warranty_cost_cents` is zero."

    Design: Difficulty/dual_variant_calc/repair_quote_customer_pay_vs_warranty_covered
    """
    product = H.new_product(api)
    customer = H.new_customer(api)
    ro, _ = H.quoted_repair(customer["id"], product["id"], DUAL_LINES, api=api)
    assert ro["quoted_total_cents"] == 21750
    assert ro["warranty_cost_cents"] == 0


def test_repair_quote_warranty_covered_waives_customer_charge(api):
    """PRD §3.4: "For a `WARRANTY_COVERED` order, the customer owes nothing, so
    `quoted_total_cents` is zero, the diagnostic fee is waived, and `warranty_cost_cents` records
    the lines total as the store's internal cost."

    Design: Difficulty/dual_variant_calc/repair_quote_customer_pay_vs_warranty_covered
    """
    product = H.new_product(api)
    customer = H.new_customer(api)
    reg = H.new_registration(product["id"], customer["id"], api)
    claim = H.new_claim(reg["id"], reg["version"], api)
    H.get_success_data(api.review_claim(claim["id"], H.TEST_USERS["associate_headers"]))
    H.get_success_data(api.resolve_claim(claim["id"], "REPAIR", H.TEST_USERS["manager_headers"]))
    ro, _ = H.quoted_repair(customer["id"], product["id"], DUAL_LINES, claim_id=claim["id"], api=api)
    assert ro["pay_mode"] == "WARRANTY_COVERED"
    assert ro["quoted_total_cents"] == 0
    assert ro["warranty_cost_cents"] == 19250


# ==========================================================================
# Queue A — combinatorial formula: nested clamp on line labor
# ==========================================================================
def test_repair_line_labor_clamps_below_min_and_above_max(api):
    """PRD §3.4: "That rounded raw figure is then clamped into `line_labor_cents` so that it is
    never below the labor floor of 1500 cents and never above the labor ceiling of 20000 cents —
    that is, the labor charged is the raw figure, but not less than 1500 and not more than 20000."

    Design: Difficulty/combinatorial_formula/repair_labor_nested_clamp_mode_a
    """
    product = H.new_product(api)
    customer = H.new_customer(api)
    lines = [
        {"repair_type": "ZIPPER", "labor_hours": 0.1, "complexity": "STANDARD", "parts_cost_cents": 0},
        {"repair_type": "WHEEL", "labor_hours": 10, "complexity": "COMPLEX", "parts_cost_cents": 0},
    ]
    ro, created = H.repair_order_with_lines(customer["id"], product["id"], lines, api=api)
    min_line, max_line = created[0], created[1]
    H.get_success_data(api.quote_repair_order(ro["id"], H.TEST_USERS["manager_headers"]))
    min_after = H.validate_success(api.get_repair_line(min_line["id"], H.TEST_USERS["associate_headers"]))
    max_after = H.validate_success(api.get_repair_line(max_line["id"], H.TEST_USERS["associate_headers"]))
    assert min_after["line_labor_cents"] == 1500
    assert max_after["line_labor_cents"] == 20000


def test_repair_quote_aggregates_clamped_lines_with_diagnostic(api):
    """PRD §3.4: "For a `CUSTOMER_PAY` order, `quoted_total_cents` is the lines total plus a
    diagnostic fee of 2500 cents, and `warranty_cost_cents` is zero."

    Design: Difficulty/combinatorial_formula/repair_labor_nested_clamp_mode_a
    """
    product = H.new_product(api)
    customer = H.new_customer(api)
    lines = [
        {"repair_type": "ZIPPER", "labor_hours": 0.1, "complexity": "STANDARD", "parts_cost_cents": 0},
        {"repair_type": "WHEEL", "labor_hours": 10, "complexity": "COMPLEX", "parts_cost_cents": 0},
    ]
    ro, _ = H.quoted_repair(customer["id"], product["id"], lines, api=api)
    assert ro["quoted_total_cents"] == 24000


# ==========================================================================
# Queue A — boundary precision: empty repair-line set rejected
# ==========================================================================
def test_quote_empty_line_set_returns_no_repair_lines(api, associate_headers):
    """PRD §3.4: "Quoting an order — moving it `INTAKE → QUOTED`, an `Associate` action —
    requires at least one repair line to exist (otherwise `ERR_NO_REPAIR_LINES`) and requires the
    product not to be `RECALLED` (otherwise `ERR_PRODUCT_RECALLED`)."

    Design: Difficulty/boundary_precision_check/repair_quote_empty_line_set_rejected
    """
    product = H.new_product(api)
    customer = H.new_customer(api)
    ro = H.new_repair_order(customer["id"], product["id"], api)
    H.validate_error(api.quote_repair_order(ro["id"], associate_headers), H.ApiErrorId.ERR_NO_REPAIR_LINES)


def test_quote_empty_line_set_leaves_order_in_intake(api, associate_headers):
    """PRD §3.4: "Quoting an order — moving it `INTAKE → QUOTED`, an `Associate` action —
    requires at least one repair line to exist (otherwise `ERR_NO_REPAIR_LINES`) and requires the
    product not to be `RECALLED` (otherwise `ERR_PRODUCT_RECALLED`)."

    Design: Difficulty/boundary_precision_check/repair_quote_empty_line_set_rejected
    """
    product = H.new_product(api)
    customer = H.new_customer(api)
    ro = H.new_repair_order(customer["id"], product["id"], api)
    H.validate_error(api.quote_repair_order(ro["id"], associate_headers), H.ApiErrorId.ERR_NO_REPAIR_LINES)
    after = H.get_repair_order(ro["id"], api)
    assert after["status"] == "INTAKE"
