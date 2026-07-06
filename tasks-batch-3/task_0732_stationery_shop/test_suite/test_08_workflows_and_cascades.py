"""Difficulty depth-probes: non-linear state machines (proof cycle, parallel dimensions),
transitive cascades, priority-pair conflicts, cross-entity state, temporal overlaps,
and compensating invariants."""
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
    create_initial_proof_payload,
    create_addressing_job_payload,
    create_line_item_payload, create_design_payload,
    advance_production, advance_addressing,
    run_production_to_completed,
)


def test_proof_cycles_changes_requested_back_to_submitted(api):
    """PRD §3.6: "A successful submission from DRAFT → SUBMITTED — or a resubmission from
    CHANGES_REQUESTED → SUBMITTED — increments Proof.current_revision_number by one,
    sets Proof.submitted_at to the current UTC instant, and (idempotently) recomputes
    Order.expected_lead_days."
    PRD §3.6: "The very first submission takes current_revision_number from zero to one,
    and no revision fee applies."

    Design: Difficulty/non_linear_state_machine/proof_cycle_changes_requested_back_to_submitted
    """
    bundle = setup_deposit_pending()
    designer = create_designer()
    des_headers = make_designer_headers(designer["id"])
    cust_headers = make_customer_headers(bundle["customer"]["id"])
    proof = get_success_data(api.create_proof(
        bundle["design"]["id"], create_initial_proof_payload(designer["id"]), des_headers,
    ))
    proof = get_success_data(api.submit_proof(proof["id"], des_headers))
    assert proof["status"] == "SUBMITTED"
    proof = get_success_data(api.request_changes_proof(proof["id"], cust_headers))
    assert proof["status"] == "CHANGES_REQUESTED"
    proof = get_success_data(api.submit_proof(proof["id"], des_headers))
    assert proof["status"] == "SUBMITTED"
    assert proof["current_revision_number"] == 2
    assert proof["revision_fee_cents"] == 0


def test_work_order_production_and_addressing_dimensions_advance_independently(api):
    """PRD §3.7: "The IN_PRODUCTION order runs against a WorkOrder. The work order is
    spawned automatically by the deposit/approval cascade in §2.10, with order_id bound
    to the parent order, production_status initialised to NOT_STARTED, and
    addressing_status initialised to NOT_APPLICABLE if the parent order has no
    AddressingJob records or to PENDING if it has at least one. The two dimensions
    advance independently."

    Design: Difficulty/non_linear_state_machine/work_order_parallel_state_dimensions_production_and_addressing
    """
    set_clock("2026-04-01T00:00:00Z")
    bundle = setup_in_production_order(quantity=150, addressing_qty=150)
    work_order = bundle["work_order"]
    assert work_order is not None
    assert work_order["production_status"] == "NOT_STARTED"
    assert work_order["addressing_status"] == "PENDING"
    # Advance production only
    advance_production(work_order, "PRINTING",
                       press_id="PRESS_B",
                       press_slot_start="2026-04-05T09:00:00Z",
                       press_slot_end="2026-04-05T13:00:00Z")
    wo_after = advance_production(work_order, "FINISHING")
    assert wo_after["production_status"] == "FINISHING"
    # Addressing dimension is UNAFFECTED
    assert wo_after["addressing_status"] == "PENDING"


def test_cancel_from_deposit_pending_cascades_proof_addressing_reserved_credit(api):
    """PRD §3.9: "A DEPOSIT_PENDING cancellation cascades the proof — whichever of DRAFT,
    SUBMITTED, or CHANGES_REQUESTED it currently occupies — to CANCELLED, cascades every
    AddressingJob on the order to CANCELLED, and releases every LineItem.quantity from
    the referenced PaperStock.reserved_units. If Order.deposit_paid_cents is strictly
    greater than zero at the moment of cancellation, the entire paid amount is moved into
    Customer.credit_balance_cents and Order.deposit_paid_cents is reset to zero — this is
    the money-conservation move described in §2.9."

    Design: Difficulty/transitive_cascade/order_cancel_from_deposit_pending_depth_three_cascade
    """
    set_clock("2026-04-01T00:00:00Z")
    # Setup: order in DEPOSIT_PENDING, deposit paid, proof SUBMITTED, AddressingJob SCHEDULED
    bundle = setup_deposit_pending_with_submitted_proof(
        quantity=150, addressing_qty=150, deposit_paid=True,
    )
    customer, order, proof, paper = (
        bundle["customer"], bundle["order"], bundle["proof"], bundle["paper"],
    )
    cust_headers = make_customer_headers(customer["id"])
    # Find the addressing job
    admin = TEST_USERS["shop_admin_headers"]
    aj_list = get_success_data(api.list_order_addressing_jobs(order["id"], admin))
    assert isinstance(aj_list, list) and len(aj_list) == 1
    aj = aj_list[0]

    # Trigger: customer cancels
    get_success_data(api.cancel_order(order["id"], cust_headers))

    # Verify cascades
    order_after = get_success_data(api.get_order(order["id"], cust_headers))
    proof_after = get_success_data(api.get_proof(proof["id"], cust_headers))
    aj_after = get_success_data(api.get_addressing_job(aj["id"], cust_headers))
    paper_after = get_success_data(api.get_paper_stock(paper["id"], cust_headers))
    customer_after = get_success_data(api.get_customer(customer["id"], admin))
    assert order_after["status"] == "CANCELLED"
    assert proof_after["status"] == "CANCELLED"
    assert aj_after["status"] == "CANCELLED"
    assert paper_after["reserved_units"] == 0
    assert order_after["deposit_paid_cents"] == 0
    assert customer_after["credit_balance_cents"] == 41250


def test_proof_expiry_cascades_order_to_cancelled_and_archives_design(api):
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
    # Submit while clock is at 2026-06-08 → expires_at = 2026-06-22
    set_clock("2026-06-08T00:00:00Z")
    proof = get_success_data(api.submit_proof(proof["id"], des_headers))
    # Advance clock past expires_at
    set_clock("2026-06-23T00:00:00Z")
    admin = TEST_USERS["shop_admin_headers"]
    proof_after = get_success_data(api.get_proof(proof["id"], admin))
    order_after = get_success_data(api.get_order(bundle["order"]["id"], admin))
    design_after = get_success_data(api.get_design(bundle["design"]["id"], admin))
    assert proof_after["status"] == "EXPIRED"
    assert order_after["status"] == "CANCELLED"
    assert design_after["status"] == "ARCHIVED"


def test_state_priority_beats_business_safety_add_line_to_cancelled_order(api):
    """PRD §2.11: "State-machine preconditions are evaluated next as a single band. Within
    that band, ERR_STALE_VERSION (the OCC check on add-line-item) surfaces alongside
    ERR_INVALID_STATE, ERR_ALREADY_TERMINAL, ERR_PROOF_EXPIRED, ERR_PROOF_NOT_APPROVED,
    ERR_ORDER_NOT_CANCELLABLE, ERR_RUSH_TOO_LATE, and ERR_DEPOSIT_NOT_PAID. Business-safety
    checks that guard catalog integrity — ERR_PAPER_DISCONTINUED and ERR_FINISH_DISCONTINUED
    — are evaluated after state preconditions."

    Design: Difficulty/priority_pair_validation_conflict/state_before_business_safety_paper_discontinued_on_terminal_order
    """
    set_clock("2026-04-01T00:00:00Z")
    customer = create_customer()
    admin = TEST_USERS["shop_admin_headers"]
    # A DISCONTINUED paper stock
    p_d = create_paper_stock(name="P9D")
    get_success_data(api.discontinue_paper_stock(p_d["id"], admin))
    # An ACTIVE paper stock for design creation
    p_ok = create_paper_stock(name="P9OK")
    finish = create_finish_option()
    pkg = create_event_package()
    design = create_design_for(customer, p_ok, finish, pkg)
    order = create_cart_order_for(customer, design)
    cust_headers = make_customer_headers(customer["id"])
    # Cancel from CART
    order = get_success_data(api.cancel_order(order["id"], cust_headers))
    # Attempt to add line item with the DISCONTINUED paper on the CANCELLED order
    payload = create_line_item_payload(
        paper_stock_id=p_d["id"], finish_option_id=finish["id"],
        quantity=150, expected_order_version=order["version"],
    )
    res = api.add_line_item(order["id"], payload, cust_headers)
    # State band wins over business-safety (PRD §2.11); PRD §3.6 further specifies
    # that any action against a resource already in a terminal state returns
    # ERR_ALREADY_TERMINAL. CANCELLED is a terminal state.
    validate_error(res, "ERR_ALREADY_TERMINAL")


def test_business_safety_beats_business_constraint_finish_discontinued_beats_qty_below_min(api):
    """PRD §2.11: "Business-safety checks that guard catalog integrity — ERR_PAPER_DISCONTINUED
    and ERR_FINISH_DISCONTINUED — are evaluated after state preconditions. Business-constraint
    checks come after that, covering quantity minimums (ERR_QUANTITY_BELOW_MIN), quantity
    validity (ERR_QUANTITY_INVALID), press-slot overlap (ERR_PRESS_SLOT_OVERLAP), addressing
    capacity (ERR_ADDRESSING_CAPACITY_EXCEEDED), and — last — reorder eligibility
    (ERR_REORDER_WINDOW_EXPIRED) and rush feasibility (ERR_RUSH_INFEASIBLE)."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_before_business_constraint_discontinued_finish_below_min_qty
    """
    set_clock("2026-04-01T00:00:00Z")
    customer = create_customer()
    admin = TEST_USERS["shop_admin_headers"]
    paper = create_paper_stock()
    # F10D discontinued (status=DISCONTINUED at creation)
    f_d = get_success_data(api.create_finish_option({
        "name": "F10D", "surcharge_cents": 100, "additional_lead_days": 5,
        "status": "DISCONTINUED",
    }, admin))
    f_ok = create_finish_option(name="F10OK")
    pkg = create_event_package(min_qty=50)
    design = create_design_for(customer, paper, f_ok, pkg)
    order = create_cart_order_for(customer, design)
    cust_headers = make_customer_headers(customer["id"])
    payload = create_line_item_payload(
        paper_stock_id=paper["id"], finish_option_id=f_d["id"],
        quantity=10, expected_order_version=order["version"],
    )
    res = api.add_line_item(order["id"], payload, cust_headers)
    validate_error(res, "ERR_FINISH_DISCONTINUED")


def test_deposit_alone_does_not_advance_order_without_proof_approval(api):
    """PRD §2.10: "Recording the last cent of the deposit sets Order.deposit_paid_at to
    the current UTC instant, increments Customer.cumulative_deposits_paid_cents by the
    deposit amount, and — if Proof.status is already APPROVED at that moment — cascades
    the parent order from DEPOSIT_PENDING to IN_PRODUCTION and spawns the same WorkOrder."

    Design: Difficulty/cross_entity_state_dependency/order_pending_to_in_production_requires_proof_approved_pair_1
    """
    set_clock("2026-04-01T00:00:00Z")
    bundle = setup_deposit_pending(quantity=150)
    customer, order = bundle["customer"], bundle["order"]
    designer = create_designer()
    des_headers = make_designer_headers(designer["id"])
    # Proof SUBMITTED (not approved)
    proof = get_success_data(api.create_proof(
        bundle["design"]["id"], create_initial_proof_payload(designer["id"]), des_headers,
    ))
    get_success_data(api.submit_proof(proof["id"], des_headers))
    # Pay deposit
    admin = TEST_USERS["shop_admin_headers"]
    get_success_data(api.simulate_payment({
        "order_id": order["id"], "amount_cents": order["deposit_due_cents"],
        "outcome": "SUCCEEDED",
    }, admin))
    order_after = get_success_data(api.get_order(order["id"], admin))
    # Deposit paid but proof still SUBMITTED → order stays DEPOSIT_PENDING
    assert order_after["status"] == "DEPOSIT_PENDING"
    assert order_after["deposit_paid_at"] is not None


def test_order_stays_in_production_while_addressing_still_in_progress(api):
    """PRD §3.7: "When production completes while addressing is NOT_APPLICABLE or already
    COMPLETED, or when addressing completes while production is already COMPLETED, the
    parent order advances from IN_PRODUCTION to READY_TO_SHIP and a Shipment is spawned."

    Design: Difficulty/cross_entity_state_dependency/shipment_dispatch_requires_work_order_both_dimensions_completed_pair_2
    """
    set_clock("2026-04-01T00:00:00Z")
    bundle = setup_in_production_order(quantity=150, addressing_qty=150)
    wo = bundle["work_order"]
    # Advance production all the way to COMPLETED
    run_production_to_completed(wo, press_id="PRESS_C",
                                press_slot_start="2026-04-05T09:00:00Z",
                                press_slot_end="2026-04-05T13:00:00Z")
    # Advance addressing to IN_PROGRESS but NOT COMPLETED
    advance_addressing(wo, "IN_PROGRESS")
    admin = TEST_USERS["shop_admin_headers"]
    order_after = get_success_data(api.get_order(bundle["order"]["id"], admin))
    # Both must complete for READY_TO_SHIP — addressing still IN_PROGRESS blocks
    assert order_after["status"] == "IN_PRODUCTION"


def test_press_slot_adjacency_at_boundary_is_rejected(api):
    """PRD §3.7: "The press slot is a closed interval — press_slot_end must be strictly
    greater than press_slot_start — and the interval must not overlap any other WorkOrder's
    already-locked interval on the same press_id. Adjacency at the boundary (one interval's
    end equal to another interval's start) is also treated as a conflict; the closed-interval
    semantics reject that too. A conflict returns ERR_PRESS_SLOT_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/press_slot_overlap_closed_interval_with_adjacency_rejection
    """
    set_clock("2026-04-01T00:00:00Z")
    # Order A locks a press slot 09:00-13:00
    bundle_a = setup_in_production_order(quantity=150)
    wo_a = bundle_a["work_order"]
    advance_production(wo_a, "PRINTING",
                       press_id="PRESS_D",
                       press_slot_start="2026-04-05T09:00:00Z",
                       press_slot_end="2026-04-05T13:00:00Z")
    # Order B attempts slot 13:00-15:00 on same press (adjacency at boundary)
    bundle_b = setup_in_production_order(quantity=150)
    wo_b = bundle_b["work_order"]
    admin = TEST_USERS["shop_admin_headers"]
    res = api.advance_production(wo_b["id"], {
        "new_status": "PRINTING", "press_id": "PRESS_D",
        "press_slot_start": "2026-04-05T13:00:00Z",
        "press_slot_end": "2026-04-05T15:00:00Z",
    }, admin)
    validate_error(res, "ERR_PRESS_SLOT_OVERLAP")


def test_addressing_daily_capacity_500_rejected_at_600(api):
    """PRD §3.7: "Advancing into IN_PROGRESS requires the parent order to have at least
    one AddressingJob, and requires that the same-day aggregate not exceed the shop's daily
    addressing capacity of five hundred pieces. Concretely, the server sums
    AddressingJob.quantity across every AddressingJob whose scheduled_date equals today
    and whose parent order's WorkOrder.addressing_status is currently IN_PROGRESS; if that
    running total plus the quantities that would enter IN_PROGRESS by this transition would
    exceed five hundred, the request is rejected with ERR_ADDRESSING_CAPACITY_EXCEEDED."

    Design: Difficulty/resource_temporal_overlap/addressing_daily_aggregate_capacity_500_units_boundary
    """
    set_clock("2026-04-01T00:00:00Z")
    # Order A: addressing qty 300, scheduled 2026-04-20
    bundle_a = setup_in_production_order(quantity=300, addressing_qty=300)
    wo_a = bundle_a["work_order"]
    admin = TEST_USERS["shop_admin_headers"]
    # Take Order A's addressing to IN_PROGRESS: production PRINTING first (need to also be in the right prod state? PRD says PENDING→IN_PROGRESS on addressing dim independent)
    # First advance production to reserve press slot
    advance_production(wo_a, "PRINTING",
                       press_id="PRESS_E",
                       press_slot_start="2026-04-05T09:00:00Z",
                       press_slot_end="2026-04-05T13:00:00Z")
    # Advance clock to same day as scheduled_date so "today" check counts A's job
    set_clock("2026-04-20T08:00:00Z")
    advance_addressing(wo_a, "IN_PROGRESS")
    # Order B: addressing qty 300, scheduled 2026-04-20
    bundle_b = setup_in_production_order(quantity=300, addressing_qty=300)
    wo_b = bundle_b["work_order"]
    advance_production(wo_b, "PRINTING",
                       press_id="PRESS_E",
                       press_slot_start="2026-04-05T14:00:00Z",
                       press_slot_end="2026-04-05T18:00:00Z")
    # Attempt IN_PROGRESS on Order B — 300 + 300 = 600 > 500
    res = api.advance_addressing(wo_b["id"], {"new_status": "IN_PROGRESS"}, admin)
    validate_error(res, "ERR_ADDRESSING_CAPACITY_EXCEEDED")


def test_cash_conservation_deposit_then_cancel_shifts_to_credit_balance(api):
    """PRD §2.9: "The two operations that touch this invariant — deposit payment and
    cancellation refund — are designed so that money moves rather than appears or
    disappears: cancelling a DEPOSIT_PENDING order with paid deposit shifts the entire
    deposit_paid_cents amount into credit_balance_cents and resets Order.deposit_paid_cents
    to zero, so the two changes cancel out in the sum above."
    PRD §2.9: "The cumulative_deposits_paid_cents field is monotonically non-decreasing:
    it is bumped every time a deposit payment succeeds and is never decremented, even
    when a subsequent cancellation refunds the money."

    Design: Difficulty/compensating_invariant/cash_conservation_deposit_pay_then_cancel_preserves_customer_ledger
    """
    set_clock("2026-04-01T00:00:00Z")
    bundle = setup_deposit_pending(quantity=150)
    customer, order = bundle["customer"], bundle["order"]
    admin = TEST_USERS["shop_admin_headers"]
    cust_headers = make_customer_headers(customer["id"])
    # Pay deposit
    get_success_data(api.simulate_payment({
        "order_id": order["id"], "amount_cents": 41250, "outcome": "SUCCEEDED",
    }, admin))
    # Cancel
    get_success_data(api.cancel_order(order["id"], cust_headers))
    # Verify
    customer_after = get_success_data(api.get_customer(customer["id"], admin))
    order_after = get_success_data(api.get_order(order["id"], admin))
    assert customer_after["credit_balance_cents"] == 41250
    assert customer_after["cumulative_deposits_paid_cents"] == 41250
    assert order_after["deposit_paid_cents"] == 0


def test_paper_reserved_units_go_to_zero_after_delivery(api):
    """PRD §2.8: "Each PaperStock exposes an aggregated read-only reserved_units field.
    This field is the sum of LineItem.quantity across every line whose parent Order is
    currently in DEPOSIT_PENDING, IN_PRODUCTION, or READY_TO_SHIP. Orders in CART do not
    reserve — a customer that has not confirmed has not committed to production. Orders
    that have SHIPPED or been DELIVERED, and orders that have been CANCELLED, release
    their reservation."

    Design: Difficulty/compensating_invariant/paper_reserved_units_conservation_confirm_then_deliver
    """
    set_clock("2026-04-01T00:00:00Z")
    # Setup: order in CART with a line qty=150
    bundle = setup_cart_order_with_line(quantity=150)
    customer, order, paper = bundle["customer"], bundle["order"], bundle["paper"]
    admin = TEST_USERS["shop_admin_headers"]
    # Before confirm: reserved 0 (CART)
    paper_before = get_success_data(api.get_paper_stock(paper["id"], admin))
    assert paper_before["reserved_units"] == 0
    # Confirm → DEPOSIT_PENDING; reserved becomes 150
    confirm_order(customer, order)
    paper_after_confirm = get_success_data(api.get_paper_stock(paper["id"], admin))
    assert paper_after_confirm["reserved_units"] == 150
    # Run whole pipeline through DELIVERED
    simulate_deposit_full(get_success_data(api.get_order(order["id"], admin)))
    designer = create_designer()
    des_headers = make_designer_headers(designer["id"])
    proof = get_success_data(api.create_proof(
        bundle["design"]["id"], create_initial_proof_payload(designer["id"]), des_headers,
    ))
    proof = get_success_data(api.submit_proof(proof["id"], des_headers))
    approve_proof(customer, proof)
    admin_hdr = TEST_USERS["shop_admin_headers"]
    wo_list = get_success_data(api.list_order_work_orders(order["id"], admin_hdr))
    wo = wo_list[0]
    run_production_to_completed(wo, press_id="PRESS_F",
                                press_slot_start="2026-04-05T09:00:00Z",
                                press_slot_end="2026-04-05T13:00:00Z")
    ship_list = get_success_data(api.list_order_shipments(order["id"], admin_hdr))
    ship = ship_list[0]
    get_success_data(api.dispatch_shipment(ship["id"], admin_hdr))
    get_success_data(api.mark_shipment_delivered(ship["id"], admin_hdr))
    # After DELIVERED: reserved back to 0
    paper_after_deliver = get_success_data(api.get_paper_stock(paper["id"], admin_hdr))
    assert paper_after_deliver["reserved_units"] == 0
