"""Calculations: rush surcharge tiers, revision fees, reorder discounts, lead days."""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    api_client, TEST_USERS,
    setup_cart_order_with_line, setup_deposit_pending,
    create_customer, create_designer, create_paper_stock, create_finish_option,
    create_event_package, create_design_for, create_cart_order_for,
    add_line_item_to_cart, set_clock, confirm_order, simulate_deposit_full,
    create_and_submit_proof, approve_proof,
    setup_ready_to_ship, setup_delivered_order,
    make_customer_headers, make_designer_headers,
    create_initial_proof_payload,
    create_addressing_job_payload,
)


def test_rush_surcharge_at_seven_day_boundary(api):
    """PRD §3.4: "the surcharge percentage is fifteen hundredths when the day count is at
    least seven and strictly less than fourteen, and thirty hundredths when the day count
    is at least three and strictly less than seven. The surcharge amount is that percentage
    applied to the base of Order.subtotal_cents minus Order.reorder_discount_cents — the
    same discounted subtotal on which the deposit is computed — and the result is rounded
    half-up to a whole number of cents."

    Design: Corner/calculations/rush_surcharge_at_seven_day_boundary_transition
    """
    set_clock("2026-04-01T00:00:00Z")
    bundle = setup_cart_order_with_line(quantity=150)
    order = bundle["order"]
    cust_headers = make_customer_headers(bundle["customer"]["id"])
    # days=7 exact: 2026-04-08 - 2026-04-01 = 7
    res = api.apply_rush(order["id"], {"rush_deadline": "2026-04-08T00:00:00Z"}, cust_headers)
    updated = validate_success(res, 200)
    # subtotal = 82500 (500*150*0.9 + 100*150), no reorder discount → 15% × 82500 = 12375
    assert updated["rush_surcharge_cents"] == 12375


def test_revision_fee_first_accrues_on_fourth_submission(api):
    """PRD §3.6: "The very first submission takes current_revision_number from zero to one,
    and no revision fee applies. From the fourth submission onward — that is, whenever the
    post-increment current_revision_number is strictly greater than three —
    Proof.revision_fee_cents accrues an additional 2500 cents (twenty-five dollars) per
    resubmission and Order.total_cents is recomputed to include the new fee."

    Design: Corner/calculations/revision_fee_starts_on_fourth_submission
    """
    bundle = setup_deposit_pending(quantity=150)
    designer = create_designer()
    des_headers = make_designer_headers(designer["id"])
    cust_headers = make_customer_headers(bundle["customer"]["id"])
    proof = get_success_data(api.create_proof(
        bundle["design"]["id"], create_initial_proof_payload(designer["id"]), des_headers,
    ))
    # Submissions 1, 2, 3 (free)
    for _ in range(3):
        proof = get_success_data(api.submit_proof(proof["id"], des_headers))
        get_success_data(api.request_changes_proof(proof["id"], cust_headers))
    # Submission 4: fee accrues
    proof = get_success_data(api.submit_proof(proof["id"], des_headers))
    assert proof["current_revision_number"] == 4
    assert proof["revision_fee_cents"] == 2500
    order = get_success_data(api.get_order(bundle["order"]["id"], cust_headers))
    # subtotal 82500 + revision fee 2500 = 85000
    assert order["total_cents"] == 85000


def test_expected_lead_days_with_addressing_and_rush(api):
    """PRD §3.4: "The expected lead-time calculation is a simple integer aggregation over
    the order's line items and add-ons: take the maximum lead_days across the paper stocks
    used on the lines, add the maximum additional_lead_days across the finish options used
    on the lines, add three additional business days if the order has any AddressingJob
    records, and subtract four business days if Order.rush_requested is true. The final
    Order.expected_lead_days is that sum with a floor of one — the field never drops below
    a single day."

    Design: Corner/calculations/expected_lead_days_with_rush_and_addressing
    """
    set_clock("2026-04-01T00:00:00Z")
    customer = create_customer()
    paper = create_paper_stock(base_price_cents=500, lead_days=7)
    finish = create_finish_option(surcharge_cents=100, additional_lead_days=5)
    pkg = create_event_package(deposit_pct=0.5, min_qty=50, proof_expiry_days=14)
    design = create_design_for(customer, paper, finish, pkg)
    order = create_cart_order_for(customer, design)
    line, order = add_line_item_to_cart(customer, order, paper, finish, quantity=150)
    cust_headers = make_customer_headers(customer["id"])
    # Add addressing job and rush
    get_success_data(api.create_addressing_job(
        order["id"],
        create_addressing_job_payload(job_type="ADDRESSING", quantity=150,
                                      scheduled_date="2026-04-15",
                                      unit_price_cents=200),
        cust_headers,
    ))
    get_success_data(api.apply_rush(order["id"],
                                     {"rush_deadline": "2026-04-12T00:00:00Z"}, cust_headers))
    order = confirm_order(customer, order)
    # 7 + 5 + 3 - 4 = 11
    assert order["expected_lead_days"] == 11
