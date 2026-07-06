"""Difficulty depth-probes for line-item pricing (list-price vs reorder-locked)
and proof expiry standard vs rush variant, plus combinatorial mode-(a) tier and
mode-(b) per-line rounding aggregation."""
import pytest
from test_helpers import (
    validate_success, get_success_data, api_client, TEST_USERS,
    create_customer, create_designer, create_paper_stock, create_finish_option,
    create_event_package, create_design_for, create_cart_order_for,
    add_line_item_to_cart, set_clock, confirm_order, simulate_deposit_full,
    create_and_submit_proof, approve_proof,
    setup_delivered_order, setup_cart_order_with_line,
    setup_deposit_pending, setup_deposit_pending_with_submitted_proof,
    make_customer_headers, make_designer_headers,
    create_initial_proof_payload, create_line_item_payload,
)


def test_reorder_locked_pricing_uses_prior_captured_base_not_live_catalog(api):
    """PRD §3.3: "The reorder-locked pricing variant applies when the parent Order was
    created with a prior_order_id that is inside the 365-day window and the new line
    item's paper_stock_id and finish_option_id both match a corresponding line on the
    prior order. In that case, the captured paper price and captured finish surcharge for
    the new line are taken from the matching prior line's own captured_base_price_cents
    and captured_finish_surcharge_cents, not from the current live catalog."
    PRD §3.1: "the update overwrites the live catalog values but does not touch
    captured_base_price_cents or captured_finish_surcharge_cents on any existing line item
    — that snapshot is exactly what makes the reorder-locked pricing variant possible."

    Design: Difficulty/dual_variant_calc/line_item_price_list_vs_reorder_locked_on_paper_price_change
    """
    set_clock("2026-03-15T00:00:00Z")
    # First order — paper base 500; run through DELIVERED
    bundle1 = setup_delivered_order(quantity=100)
    customer = bundle1["customer"]
    paper = bundle1["paper"]
    finish = bundle1["finish"]
    pkg = bundle1["package"]
    o1 = bundle1["order"]
    admin = TEST_USERS["shop_admin_headers"]

    # PATCH paper price 500 -> 800
    patch_res = api.patch_paper_stock(paper["id"], {"base_price_cents": 800}, admin)
    validate_success(patch_res, 200)

    # Advance clock to still inside the 365-day window
    set_clock("2026-05-01T00:00:00Z")

    # New design + order with prior_order_id
    d2 = create_design_for(customer, paper, finish, pkg)
    cust_headers = make_customer_headers(customer["id"])
    o2 = get_success_data(api.create_order({
        "customer_id": customer["id"], "design_id": d2["id"],
        "prior_order_id": o1["id"],
    }, cust_headers))
    # Add matching line item (same paper, finish, qty=100)
    line = get_success_data(api.add_line_item(o2["id"], create_line_item_payload(
        paper_stock_id=paper["id"], finish_option_id=finish["id"],
        quantity=100, expected_order_version=o2["version"],
    ), cust_headers))
    # Reorder-locked: captured_base = 500 (prior line's), NOT live 800
    # line = 500*100*0.9 + 100*100 = 45000 + 10000 = 55000
    assert line["line_price_cents"] == 55000
    # subtotal same
    o2_after = get_success_data(api.get_order(o2["id"], cust_headers))
    assert o2_after["subtotal_cents"] == 55000
    # reorder_discount will be 0 while CART (locked at confirm), so confirm and check
    o2_confirmed = confirm_order(customer, o2_after)
    # 10% of 55000 = 5500
    assert o2_confirmed["reorder_discount_cents"] == 5500


def test_proof_expiry_rush_variant_halves_expiry_window(api):
    """PRD §3.6: "The standard variant, used when Order.rush_requested is false, adds
    EventPackage.proof_expiry_days days to the submission timestamp. The rush variant,
    used when Order.rush_requested is true, halves the package's proof-expiry window and
    rounds the halved value up to a whole number of days — that is, the number of days
    added is the ceiling of EventPackage.proof_expiry_days divided by two."

    Design: Difficulty/dual_variant_calc/proof_expires_at_standard_vs_rush_variant_on_lifecycle_entity
    """
    set_clock("2026-06-01T00:00:00Z")
    customer = create_customer()
    paper = create_paper_stock()
    finish = create_finish_option()
    pkg = create_event_package(proof_expiry_days=14)
    design = create_design_for(customer, paper, finish, pkg)
    order = create_cart_order_for(customer, design)
    line, order = add_line_item_to_cart(customer, order, paper, finish, quantity=150)
    cust_headers = make_customer_headers(customer["id"])
    # Rush before confirm
    get_success_data(api.apply_rush(order["id"],
                                     {"rush_deadline": "2026-06-08T00:00:00Z"}, cust_headers))
    order = confirm_order(customer, order)
    # Advance to submission time
    set_clock("2026-06-15T00:00:00Z")
    designer = create_designer()
    des_headers = make_designer_headers(designer["id"])
    proof = get_success_data(api.create_proof(
        design["id"], create_initial_proof_payload(designer["id"]), des_headers,
    ))
    proof = get_success_data(api.submit_proof(proof["id"], des_headers))
    # 2026-06-15 + ceil(14/2) = 2026-06-15 + 7 = 2026-06-22
    expires_at = proof["expires_at"]
    assert expires_at.startswith("2026-06-22"), f"expected 2026-06-22..., got {expires_at}"


def test_line_price_tier_multiplier_at_qty_100_selects_nine_tenths_band(api):
    """PRD §3.3: "the system selects a tier multiplier by locating the quantity band into
    which quantity falls — the bands are 1 to 49 with multiplier one, 50 to 99 with
    multiplier one, 100 to 199 with multiplier nine-tenths, 200 to 499 with multiplier
    eight-tenths, and 500 or more with multiplier seven-tenths."

    Design: Difficulty/combinatorial_formula/line_item_tiered_pricing_three_input_branch_mode_a
    """
    set_clock("2026-04-01T00:00:00Z")
    customer = create_customer()
    paper = create_paper_stock(base_price_cents=500, lead_days=7)
    finish = create_finish_option(surcharge_cents=100, additional_lead_days=5)
    pkg = create_event_package(min_qty=50)
    design = create_design_for(customer, paper, finish, pkg)
    order = create_cart_order_for(customer, design)
    line, _ = add_line_item_to_cart(customer, order, paper, finish, quantity=150)
    # 500*150*0.9 + 100*150 = 67500 + 15000 = 82500
    assert line["line_price_cents"] == 82500


def test_order_subtotal_is_per_line_rounded_then_summed(api):
    """PRD §3.3: "The per-line rounding is deliberate: order aggregation later is a sum
    of the already-rounded per-line values, never a fresh round on the total, because the
    tier-multiplier arithmetic across a whole order would otherwise drift."
    PRD §3.3: "The paper component is the captured paper price multiplied by the quantity
    multiplied by the tier multiplier, and this intermediate product is rounded half-up to
    a whole number of cents before it goes any further."

    Design: Difficulty/combinatorial_formula/order_subtotal_per_line_then_sum_rounding_order_mode_b
    """
    set_clock("2026-04-01T00:00:00Z")
    customer = create_customer()
    paper = create_paper_stock(base_price_cents=333, lead_days=7)
    finish = create_finish_option(surcharge_cents=100, additional_lead_days=5)
    pkg = create_event_package(min_qty=50)
    design = create_design_for(customer, paper, finish, pkg)
    order = create_cart_order_for(customer, design)
    line1, order = add_line_item_to_cart(customer, order, paper, finish, quantity=100)
    # Paper component: 333 * 100 * 0.9 = 29970.0 → 29970; finish 100*100=10000; sum 39970
    assert line1["line_price_cents"] == 39970
    line2, order = add_line_item_to_cart(customer, order, paper, finish, quantity=100)
    assert line2["line_price_cents"] == 39970
    # Order subtotal = 39970 + 39970 = 79940 (per-line then sum)
    cust_headers = make_customer_headers(customer["id"])
    order_after = get_success_data(api.get_order(order["id"], cust_headers))
    assert order_after["subtotal_cents"] == 79940


def test_line_price_at_quantity_boundary_100_exact(api):
    """PRD §3.3: "the bands are 1 to 49 with multiplier one, 50 to 99 with multiplier one,
    100 to 199 with multiplier nine-tenths, 200 to 499 with multiplier eight-tenths, and
    500 or more with multiplier seven-tenths."

    Design: Difficulty/boundary_precision_check/quantity_tier_boundary_at_100_exact
    """
    set_clock("2026-04-01T00:00:00Z")
    customer = create_customer()
    paper = create_paper_stock(base_price_cents=500, lead_days=7)
    finish = create_finish_option(surcharge_cents=100, additional_lead_days=5)
    pkg = create_event_package(min_qty=50)
    design = create_design_for(customer, paper, finish, pkg)
    order = create_cart_order_for(customer, design)
    line, _ = add_line_item_to_cart(customer, order, paper, finish, quantity=100)
    # 500*100*0.9 + 100*100 = 45000 + 10000 = 55000
    assert line["line_price_cents"] == 55000


def test_rush_deadline_boundary_at_14_days_rejected_and_13_days_accepted(api):
    """PRD §3.4: "The system computes the number of whole days between rush_deadline and
    the current UTC time, and rejects the request with ERR_RUSH_INFEASIBLE unless that
    number is at least three and strictly less than fourteen: a deadline fourteen or more
    days out is too far away for the rush tier to apply, and a deadline fewer than three
    days out is infeasible. Within the feasible range, the surcharge percentage is fifteen
    hundredths when the day count is at least seven and strictly less than fourteen, and
    thirty hundredths when the day count is at least three and strictly less than seven."

    Design: Difficulty/boundary_precision_check/rush_deadline_boundary_at_14_days_reject_and_13_days_accept
    """
    from test_helpers import validate_error
    set_clock("2026-04-01T00:00:00Z")
    bundle = setup_cart_order_with_line(quantity=150)
    cust_headers = make_customer_headers(bundle["customer"]["id"])
    order_id = bundle["order"]["id"]
    # days=14 exact → reject
    res14 = api.apply_rush(order_id, {"rush_deadline": "2026-04-15T00:00:00Z"}, cust_headers)
    validate_error(res14, "ERR_RUSH_INFEASIBLE")
    # days=13 → accept, 15% of 82500 = 12375
    res13 = api.apply_rush(order_id, {"rush_deadline": "2026-04-14T00:00:00Z"}, cust_headers)
    updated = validate_success(res13, 200)
    assert updated["rush_surcharge_cents"] == 12375
