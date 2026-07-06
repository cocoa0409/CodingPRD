"""Second-pass tests for each difficulty instance (Coverage: ≥2 tests per instance).

Every test here re-asserts a distinct sub-fact of its cited difficulty instance
that PRD.md verbatim-covers and uniquely-derives.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, TEST_USERS,
    create_customer, create_designer, create_paper_stock, create_finish_option,
    create_event_package, create_design_for, create_cart_order_for,
    add_line_item_to_cart, set_clock, confirm_order, simulate_deposit_full,
    create_and_submit_proof, approve_proof, create_draft_proof,
    setup_deposit_pending, setup_deposit_pending_with_submitted_proof,
    setup_in_production_order, setup_ready_to_ship, setup_delivered_order,
    setup_cart_order_with_line, setup_deposit_paid_no_proof,
    make_customer_headers, make_designer_headers,
    create_initial_proof_payload, create_line_item_payload,
    advance_production, advance_addressing,
    run_production_to_completed,
    create_addressing_job_payload,
)


# ─── Rule 1: dual-variant calc ─────────────────────────

def test_first_time_order_uses_list_price_reading_live_catalog(api):
    """PRD §3.3: "A first-time order (no prior_order_id), or a reorder outside the 365-day
    window, uses the list-price variant that reads the live catalog."
    PRD §3.3: "On success, the server stamps the new LineItem with a snapshot of the live
    catalog: captured_base_price_cents is set from the current PaperStock.base_price_cents,
    and captured_finish_surcharge_cents from the current FinishOption.surcharge_cents."

    Design: Difficulty/dual_variant_calc/line_item_price_list_vs_reorder_locked_on_paper_price_change
    """
    set_clock("2026-04-01T00:00:00Z")
    customer = create_customer()
    paper = create_paper_stock(base_price_cents=800, lead_days=7)
    finish = create_finish_option(surcharge_cents=100, additional_lead_days=5)
    pkg = create_event_package(min_qty=50)
    design = create_design_for(customer, paper, finish, pkg)
    order = create_cart_order_for(customer, design)  # no prior_order_id
    line, _ = add_line_item_to_cart(customer, order, paper, finish, quantity=100)
    # list_price variant reads live 800: 800*100*0.9 + 100*100 = 72000 + 10000 = 82000
    assert line["line_price_cents"] == 82000


def test_proof_expiry_standard_variant_full_expiry_days_no_rush(api):
    """PRD §3.6: "The standard variant, used when Order.rush_requested is false, adds
    EventPackage.proof_expiry_days days to the submission timestamp."

    Design: Difficulty/dual_variant_calc/proof_expires_at_standard_vs_rush_variant_on_lifecycle_entity
    """
    set_clock("2026-06-15T00:00:00Z")
    bundle = setup_deposit_pending(quantity=150)
    designer = create_designer()
    des_headers = make_designer_headers(designer["id"])
    proof = get_success_data(api.create_proof(
        bundle["design"]["id"], create_initial_proof_payload(designer["id"]), des_headers,
    ))
    proof = get_success_data(api.submit_proof(proof["id"], des_headers))
    # Standard: 14 days added → 2026-06-29
    assert proof["expires_at"].startswith("2026-06-29"), \
        f"expected 2026-06-29..., got {proof['expires_at']}"


# ─── Rule 2: combinatorial formula ─────────────────────

def test_line_price_qty_99_stays_in_full_price_band(api):
    """PRD §3.3: "the bands are 1 to 49 with multiplier one, 50 to 99 with multiplier one,
    100 to 199 with multiplier nine-tenths, 200 to 499 with multiplier eight-tenths, and
    500 or more with multiplier seven-tenths."

    Design: Difficulty/combinatorial_formula/line_item_tiered_pricing_three_input_branch_mode_a
    """
    set_clock("2026-04-01T00:00:00Z")
    customer = create_customer()
    paper = create_paper_stock(base_price_cents=500, lead_days=7)
    finish = create_finish_option(surcharge_cents=100, additional_lead_days=5)
    pkg = create_event_package(min_qty=50)
    design = create_design_for(customer, paper, finish, pkg)
    order = create_cart_order_for(customer, design)
    line, _ = add_line_item_to_cart(customer, order, paper, finish, quantity=99)
    # 500*99*1.0 + 100*99 = 49500 + 9900 = 59400
    assert line["line_price_cents"] == 59400


def test_order_total_equals_subtotal_when_no_discount_no_rush_no_fee(api):
    """PRD §3.5: "Order.total_cents — the running total after every adjustment — is
    Order.subtotal_cents minus Order.reorder_discount_cents plus Order.rush_surcharge_cents
    plus any Proof.revision_fee_cents accrued on the associated proof (zero when no proof
    yet exists). It is recomputed on every line-item change, on every rush application,
    on confirmation, and every time a revision fee accrues."

    Design: Difficulty/combinatorial_formula/order_subtotal_per_line_then_sum_rounding_order_mode_b
    """
    set_clock("2026-04-01T00:00:00Z")
    bundle = setup_cart_order_with_line(quantity=150)
    customer, order = bundle["customer"], bundle["order"]
    cust_headers = make_customer_headers(customer["id"])
    order_after = get_success_data(api.get_order(order["id"], cust_headers))
    # subtotal 82500, no discount, no rush, no proof → total 82500
    assert order_after["subtotal_cents"] == 82500
    assert order_after["total_cents"] == 82500


# ─── Rule 3: non-linear state machine ──────────────────

def test_third_revision_still_free_no_fee_after_three_submissions(api):
    """PRD §3.6: "The very first submission takes current_revision_number from zero to one,
    and no revision fee applies. From the fourth submission onward — that is, whenever the
    post-increment current_revision_number is strictly greater than three —
    Proof.revision_fee_cents accrues an additional 2500 cents (twenty-five dollars) per
    resubmission and Order.total_cents is recomputed to include the new fee."

    Design: Difficulty/non_linear_state_machine/proof_cycle_changes_requested_back_to_submitted
    """
    bundle = setup_deposit_pending()
    designer = create_designer()
    des_headers = make_designer_headers(designer["id"])
    cust_headers = make_customer_headers(bundle["customer"]["id"])
    proof = get_success_data(api.create_proof(
        bundle["design"]["id"], create_initial_proof_payload(designer["id"]), des_headers,
    ))
    proof = get_success_data(api.submit_proof(proof["id"], des_headers))  # rev 1
    proof = get_success_data(api.request_changes_proof(proof["id"], cust_headers))
    proof = get_success_data(api.submit_proof(proof["id"], des_headers))  # rev 2
    proof = get_success_data(api.request_changes_proof(proof["id"], cust_headers))
    proof = get_success_data(api.submit_proof(proof["id"], des_headers))  # rev 3
    assert proof["current_revision_number"] == 3
    assert proof["revision_fee_cents"] == 0


def test_work_order_addressing_dimension_pending_when_addressing_job_exists(api):
    """PRD §3.7: "The work order is spawned automatically by the deposit/approval cascade
    in §2.10, with order_id bound to the parent order, production_status initialised to
    NOT_STARTED, and addressing_status initialised to NOT_APPLICABLE if the parent order
    has no AddressingJob records or to PENDING if it has at least one."

    Design: Difficulty/non_linear_state_machine/work_order_parallel_state_dimensions_production_and_addressing
    """
    set_clock("2026-04-01T00:00:00Z")
    bundle = setup_in_production_order(quantity=150, addressing_qty=150)
    wo = bundle["work_order"]
    assert wo["production_status"] == "NOT_STARTED"
    assert wo["addressing_status"] == "PENDING"


# ─── Rule 4: transitive cascade ────────────────────────

def test_cart_cancel_cascades_only_to_addressing_jobs(api):
    """PRD §3.9: "A CART cancellation cascades every AddressingJob on the order to
    CANCELLED (there is no proof yet to cascade, and no work order or shipment yet exists)."

    Design: Difficulty/transitive_cascade/order_cancel_from_deposit_pending_depth_three_cascade
    """
    set_clock("2026-04-01T00:00:00Z")
    customer = create_customer()
    paper = create_paper_stock()
    finish = create_finish_option()
    pkg = create_event_package()
    design = create_design_for(customer, paper, finish, pkg)
    order = create_cart_order_for(customer, design)
    line, order = add_line_item_to_cart(customer, order, paper, finish, quantity=150)
    cust_headers = make_customer_headers(customer["id"])
    aj = get_success_data(api.create_addressing_job(
        order["id"], create_addressing_job_payload(quantity=150), cust_headers,
    ))
    order_cancelled = get_success_data(api.cancel_order(order["id"], cust_headers))
    assert order_cancelled["status"] == "CANCELLED"
    aj_after = get_success_data(api.get_addressing_job(aj["id"], cust_headers))
    assert aj_after["status"] == "CANCELLED"


def test_proof_expiry_side_effect_archives_design(api):
    """PRD §3.6: "When the current UTC time passes Proof.expires_at while the proof is
    still in SUBMITTED, the system observes the expiry on the next read and drives the
    proof to EXPIRED, cascades the parent order to CANCELLED, and archives the design."

    Design: Difficulty/transitive_cascade/proof_expiry_auto_cascade_depth_two_from_clock
    """
    set_clock("2026-06-01T00:00:00Z")
    bundle = setup_deposit_pending()
    designer = create_designer()
    des_headers = make_designer_headers(designer["id"])
    proof = get_success_data(api.create_proof(
        bundle["design"]["id"], create_initial_proof_payload(designer["id"]), des_headers,
    ))
    set_clock("2026-06-08T00:00:00Z")
    proof = get_success_data(api.submit_proof(proof["id"], des_headers))
    # Advance past expires_at (2026-06-22)
    set_clock("2026-06-25T00:00:00Z")
    admin = TEST_USERS["shop_admin_headers"]
    # PRD §3.6: "the system observes the expiry on the next read" — trigger the
    # expiry observation by reading the proof first, then verify the design cascade.
    get_success_data(api.get_proof(proof["id"], admin))
    design_after = get_success_data(api.get_design(bundle["design"]["id"], admin))
    assert design_after["status"] == "ARCHIVED"


# ─── Rule 5: priority-pair validation conflict ─────────

def test_state_before_business_safety_add_discontinued_finish_to_cancelled_order(api):
    """PRD §2.11: "State-machine preconditions are evaluated next as a single band."
    PRD §2.11: "Business-safety checks that guard catalog integrity —
    ERR_PAPER_DISCONTINUED and ERR_FINISH_DISCONTINUED — are evaluated after state
    preconditions."

    Design: Difficulty/priority_pair_validation_conflict/state_before_business_safety_paper_discontinued_on_terminal_order
    """
    customer = create_customer()
    admin = TEST_USERS["shop_admin_headers"]
    paper = create_paper_stock()
    f_disc = get_success_data(api.create_finish_option({
        "name": "F_disc_alt", "surcharge_cents": 100, "additional_lead_days": 5,
        "status": "DISCONTINUED",
    }, admin))
    f_ok = create_finish_option(name="F_ok_alt")
    pkg = create_event_package(min_qty=50)
    design = create_design_for(customer, paper, f_ok, pkg)
    order = create_cart_order_for(customer, design)
    cust_headers = make_customer_headers(customer["id"])
    # Cancel to reach terminal CANCELLED
    order = get_success_data(api.cancel_order(order["id"], cust_headers))
    # Attempt add-line-item with DISCONTINUED finish on CANCELLED order — state wins
    payload = create_line_item_payload(
        paper_stock_id=paper["id"], finish_option_id=f_disc["id"],
        quantity=150, expected_order_version=order["version"],
    )
    res = api.add_line_item(order["id"], payload, cust_headers)
    # State band wins over business-safety (PRD §2.11); PRD §3.6 further specifies
    # that any action against a resource already in a terminal state returns
    # ERR_ALREADY_TERMINAL. CANCELLED is a terminal state.
    validate_error(res, "ERR_ALREADY_TERMINAL")


def test_discontinued_finish_alone_returns_finish_discontinued(api):
    """PRD §3.1: "Both ERR_PAPER_DISCONTINUED and ERR_FINISH_DISCONTINUED fire on line-item
    addition, on order confirmation, and on design creation."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_before_business_constraint_discontinued_finish_below_min_qty
    """
    customer = create_customer()
    admin = TEST_USERS["shop_admin_headers"]
    paper = create_paper_stock()
    f_d = get_success_data(api.create_finish_option({
        "name": "F_disc", "surcharge_cents": 100, "additional_lead_days": 5,
        "status": "DISCONTINUED",
    }, admin))
    f_ok = create_finish_option(name="F_ok")
    pkg = create_event_package(min_qty=50)
    design = create_design_for(customer, paper, f_ok, pkg)
    order = create_cart_order_for(customer, design)
    cust_headers = make_customer_headers(customer["id"])
    payload = create_line_item_payload(
        paper_stock_id=paper["id"], finish_option_id=f_d["id"],
        quantity=150,  # meets min_qty
        expected_order_version=order["version"],
    )
    res = api.add_line_item(order["id"], payload, cust_headers)
    validate_error(res, "ERR_FINISH_DISCONTINUED")


# ─── Rule 6: boundary precision check ──────────────────

def test_line_price_at_qty_99_uses_full_multiplier(api):
    """PRD §3.3: "the bands are 1 to 49 with multiplier one, 50 to 99 with multiplier one,
    100 to 199 with multiplier nine-tenths, 200 to 499 with multiplier eight-tenths, and
    500 or more with multiplier seven-tenths."

    Design: Difficulty/boundary_precision_check/quantity_tier_boundary_at_100_exact
    """
    set_clock("2026-04-01T00:00:00Z")
    customer = create_customer()
    paper = create_paper_stock(base_price_cents=500)
    finish = create_finish_option(surcharge_cents=100)
    pkg = create_event_package(min_qty=50)
    design = create_design_for(customer, paper, finish, pkg)
    order = create_cart_order_for(customer, design)
    line, _ = add_line_item_to_cart(customer, order, paper, finish, quantity=99)
    # 500*99*1.0 + 100*99 = 49500 + 9900 = 59400
    assert line["line_price_cents"] == 59400


def test_rush_at_13_days_uses_15_percent_tier(api):
    """PRD §3.4: "Within the feasible range, the surcharge percentage is fifteen hundredths
    when the day count is at least seven and strictly less than fourteen, and thirty
    hundredths when the day count is at least three and strictly less than seven."

    Design: Difficulty/boundary_precision_check/rush_deadline_boundary_at_14_days_reject_and_13_days_accept
    """
    set_clock("2026-04-01T00:00:00Z")
    bundle = setup_cart_order_with_line(quantity=150)
    cust_headers = make_customer_headers(bundle["customer"]["id"])
    # days=13 → 15% × 82500 = 12375
    res = api.apply_rush(bundle["order"]["id"],
                         {"rush_deadline": "2026-04-14T00:00:00Z"}, cust_headers)
    updated = validate_success(res, 200)
    assert updated["rush_surcharge_cents"] == 12375
    assert updated["rush_requested"] is True


# ─── Rule 7: cross-entity state dependency ─────────────

def test_proof_approve_alone_does_not_advance_order_without_deposit_paid(api):
    """PRD §2.10: "Approving a proof sets Proof.approved_at to the current UTC instant,
    transitions Design.status to APPROVED, and — if Order.deposit_paid_at is already set
    at that moment — cascades the parent order from DEPOSIT_PENDING to IN_PRODUCTION and
    spawns a WorkOrder (with production_status of NOT_STARTED, and addressing_status of
    either NOT_APPLICABLE when the order has no addressing jobs or PENDING when it has
    at least one)."

    Design: Difficulty/cross_entity_state_dependency/order_pending_to_in_production_requires_proof_approved_pair_1
    """
    set_clock("2026-04-01T00:00:00Z")
    # Order in DEPOSIT_PENDING, deposit NOT paid, proof SUBMITTED then APPROVED
    bundle = setup_deposit_pending_with_submitted_proof(deposit_paid=False)
    proof = approve_proof(bundle["customer"], bundle["proof"])
    assert proof["status"] == "APPROVED"
    admin = TEST_USERS["shop_admin_headers"]
    order_after = get_success_data(api.get_order(bundle["order"]["id"], admin))
    # Proof approved but no deposit → order still DEPOSIT_PENDING
    assert order_after["status"] == "DEPOSIT_PENDING"
    assert order_after["deposit_paid_at"] is None


def test_completing_addressing_when_production_done_promotes_order_to_ready_to_ship(api):
    """PRD §3.7: "When production completes while addressing is NOT_APPLICABLE or already
    COMPLETED, or when addressing completes while production is already COMPLETED, the
    parent order advances from IN_PRODUCTION to READY_TO_SHIP and a Shipment is spawned."

    Design: Difficulty/cross_entity_state_dependency/shipment_dispatch_requires_work_order_both_dimensions_completed_pair_2
    """
    set_clock("2026-04-01T00:00:00Z")
    bundle = setup_in_production_order(quantity=150, addressing_qty=150)
    wo = bundle["work_order"]
    run_production_to_completed(wo, press_id="PRESS_XC",
                                press_slot_start="2026-04-05T09:00:00Z",
                                press_slot_end="2026-04-05T13:00:00Z")
    # Advance addressing to COMPLETED via IN_PROGRESS
    advance_addressing(wo, "IN_PROGRESS")
    advance_addressing(wo, "COMPLETED")
    admin = TEST_USERS["shop_admin_headers"]
    order_after = get_success_data(api.get_order(bundle["order"]["id"], admin))
    assert order_after["status"] == "READY_TO_SHIP"


# ─── Rule 8: resource temporal overlap ─────────────────

def test_press_slot_direct_overlap_is_rejected(api):
    """PRD §3.7: "the interval must not overlap any other WorkOrder's already-locked
    interval on the same press_id."

    Design: Difficulty/resource_temporal_overlap/press_slot_overlap_closed_interval_with_adjacency_rejection
    """
    set_clock("2026-04-01T00:00:00Z")
    bundle_a = setup_in_production_order(quantity=150)
    wo_a = bundle_a["work_order"]
    advance_production(wo_a, "PRINTING",
                       press_id="PRESS_OV",
                       press_slot_start="2026-04-05T09:00:00Z",
                       press_slot_end="2026-04-05T13:00:00Z")
    bundle_b = setup_in_production_order(quantity=150)
    wo_b = bundle_b["work_order"]
    admin = TEST_USERS["shop_admin_headers"]
    # Direct overlap 10:00-12:00
    res = api.advance_production(wo_b["id"], {
        "new_status": "PRINTING", "press_id": "PRESS_OV",
        "press_slot_start": "2026-04-05T10:00:00Z",
        "press_slot_end": "2026-04-05T12:00:00Z",
    }, admin)
    validate_error(res, "ERR_PRESS_SLOT_OVERLAP")


def test_addressing_capacity_at_500_boundary_allows_within_limit(api):
    """PRD §3.7: "Advancing into IN_PROGRESS requires the parent order to have at least
    one AddressingJob, and requires that the same-day aggregate not exceed the shop's daily
    addressing capacity of five hundred pieces."

    Design: Difficulty/resource_temporal_overlap/addressing_daily_aggregate_capacity_500_units_boundary
    """
    set_clock("2026-04-01T00:00:00Z")
    # A single order with addressing qty 500 (right at the limit)
    bundle = setup_in_production_order(quantity=500, addressing_qty=500)
    wo = bundle["work_order"]
    advance_production(wo, "PRINTING",
                       press_id="PRESS_500",
                       press_slot_start="2026-04-05T09:00:00Z",
                       press_slot_end="2026-04-05T13:00:00Z")
    # Advance clock to same day as scheduled_date so it counts as "today"
    set_clock("2026-04-20T08:00:00Z")
    admin = TEST_USERS["shop_admin_headers"]
    # Exactly 500 should be allowed (not exceed)
    res = api.advance_addressing(wo["id"], {"new_status": "IN_PROGRESS"}, admin)
    updated = validate_success(res, 200)
    assert updated["addressing_status"] == "IN_PROGRESS"


# ─── Rule 9: compensating invariant ────────────────────

def test_cumulative_deposits_paid_is_monotonically_non_decreasing_after_refund(api):
    """PRD §2.9: "The cumulative_deposits_paid_cents field is monotonically non-decreasing:
    it is bumped every time a deposit payment succeeds and is never decremented, even when
    a subsequent cancellation refunds the money."

    Design: Difficulty/compensating_invariant/cash_conservation_deposit_pay_then_cancel_preserves_customer_ledger
    """
    set_clock("2026-04-01T00:00:00Z")
    bundle = setup_deposit_pending(quantity=150)
    customer, order = bundle["customer"], bundle["order"]
    admin = TEST_USERS["shop_admin_headers"]
    cust_headers = make_customer_headers(customer["id"])
    # Pay deposit → cumulative bumps to 41250
    get_success_data(api.simulate_payment({
        "order_id": order["id"], "amount_cents": 41250, "outcome": "SUCCEEDED",
    }, admin))
    c_after_pay = get_success_data(api.get_customer(customer["id"], admin))
    assert c_after_pay["cumulative_deposits_paid_cents"] == 41250
    # Cancel order (refunds to credit_balance) → cumulative unchanged
    get_success_data(api.cancel_order(order["id"], cust_headers))
    c_after_cancel = get_success_data(api.get_customer(customer["id"], admin))
    assert c_after_cancel["cumulative_deposits_paid_cents"] == 41250  # not decremented


def test_paper_reserved_units_bumped_at_confirm_by_line_quantity(api):
    """PRD §2.10: "Confirming an order creates a fresh Proof (with status DRAFT and
    current_revision_number of zero, and designer_id left unset), advances Design.status
    to PROOFING, snapshots Order.event_package_id from the Design, and, for each LineItem,
    adds LineItem.quantity to the referenced PaperStock.reserved_units."

    Design: Difficulty/compensating_invariant/paper_reserved_units_conservation_confirm_then_deliver
    """
    set_clock("2026-04-01T00:00:00Z")
    bundle = setup_cart_order_with_line(quantity=175)
    customer, order, paper = bundle["customer"], bundle["order"], bundle["paper"]
    cust_headers = make_customer_headers(customer["id"])
    admin = TEST_USERS["shop_admin_headers"]
    paper_before = get_success_data(api.get_paper_stock(paper["id"], admin))
    assert paper_before["reserved_units"] == 0
    confirm_order(customer, order)
    paper_after = get_success_data(api.get_paper_stock(paper["id"], admin))
    assert paper_after["reserved_units"] == 175
