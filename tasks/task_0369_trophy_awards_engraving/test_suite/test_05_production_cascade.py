"""Production pipeline: start-production gate, assemble cascade, bubble-up, proof-revert (A + B)."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    make_customer_headers,
    make_staff_headers,
    fixtures,
    factories,
)

STAFF = make_staff_headers()


def _alloc_for_line(api, line_id, headers):
    data, _meta = validate_paginated(api.list_line_component_allocations(line_id, headers))
    return data


# ─── transitive_cascade: assemble -> consume -> decrement -> bubble READY (depth 3) ───
def test_assemble_consume_decrement_bubble_ready_depth3(api):
    """PRD §3.7: "On success the line's `assembled_count` is set to its `quantity`, and each
    of the line's allocations advances `RESERVED → CONSUMED`: every affected component's
    `on_hand_qty` and `allocated_qty` are both reduced by the allocation's `qty`, and its
    `available_qty` and `low_stock` are recomputed."
    PRD §3.7: "When the assembly that finishes a line leaves every line on the order in
    `ASSEMBLED`, the order auto-advances `IN_PRODUCTION → READY`, stamping `ready_at` with
    the current time and incrementing the order's `version`."

    Design: Difficulty/transitive_cascade/assemble_consume_decrement_bubble_ready_depth3
    """
    ctx = fixtures.setup_in_production_order(
        product_overrides={"base_price_cents": 4000, "standard_lead_days": 3}, on_hand_qty=10
    )
    line, cust_obj = ctx["line"], ctx["customer"]
    cust = make_customer_headers(cust_obj["id"])
    assembled = validate_success(api.assemble_line(line["id"], STAFF))
    assert assembled["line_status"] == "ASSEMBLED"
    allocs = _alloc_for_line(api, line["id"], STAFF)
    assert len(allocs) == 1
    assert allocs[0]["alloc_status"] == "CONSUMED"
    comp = validate_success(api.get_component(ctx["component"]["id"], STAFF))
    assert comp["on_hand_qty"] == 9
    assert comp["allocated_qty"] == 0
    assert comp["available_qty"] == 9
    order = validate_success(api.get_order(ctx["order"]["id"], cust))
    assert order["production_status"] == "READY"


def test_assemble_single_line_bubbles_order_ready(api):
    """PRD §3.7: "When the assembly that finishes a line leaves every line on the order in
    `ASSEMBLED`, the order auto-advances `IN_PRODUCTION → READY`, stamping `ready_at` with
    the current time and incrementing the order's `version`."

    Design: Difficulty/transitive_cascade/assemble_consume_decrement_bubble_ready_depth3
    """
    ctx = fixtures.setup_in_production_order(
        product_overrides={"base_price_cents": 4000, "standard_lead_days": 3}, on_hand_qty=10
    )
    line, cust_obj = ctx["line"], ctx["customer"]
    cust = make_customer_headers(cust_obj["id"])
    validate_success(api.assemble_line(line["id"], STAFF))
    order = validate_success(api.get_order(ctx["order"]["id"], cust))
    assert order["production_status"] == "READY"
    assert order["ready_at"] is not None


# ─── transitive_cascade: proof request-changes reverts in-flight line (depth 2) ───
def test_request_changes_reverts_line_depth2(api):
    """PRD §3.3: "if the owning line is currently in `line_status` `ALLOCATED` or
    `ENGRAVING`, the line reverts to `PENDING`, its `assembled_count` is reset to 0, and any
    engraving-stage progress is discarded — but the line's reserved component allocations
    are kept in `RESERVED` and are not released."

    Design: Difficulty/transitive_cascade/request_changes_reverts_line_depth2
    """
    ctx = fixtures.setup_in_production_order(
        product_overrides={"base_price_cents": 4000, "standard_lead_days": 3}, on_hand_qty=10
    )
    line, cust_obj = ctx["line"], ctx["customer"]
    cust = make_customer_headers(cust_obj["id"])
    # Line is ENGRAVING with approved proof P1. Create + send a second proof P2, then
    # request changes on P2 to revert the in-flight line.
    p2 = validate_success(
        api.create_proof(line["id"], factories.create_proof_payload(proof_kind="LOGO", content_ref="logo-v2"), STAFF),
        201,
    )
    validate_success(api.send_proof(line["id"], p2["id"], STAFF))
    changed = validate_success(api.request_changes_proof(line["id"], p2["id"], cust))
    assert changed["proof_status"] == "CHANGES_REQUESTED"
    line_reread = validate_success(api.get_order_line(line["id"], cust))
    assert line_reread["line_status"] == "PENDING"
    assert line_reread["assembled_count"] == 0
    allocs = _alloc_for_line(api, line["id"], STAFF)
    assert allocs[0]["alloc_status"] == "RESERVED"


def test_request_changes_keeps_allocations_reserved(api):
    """PRD §3.3: "but the line's reserved component allocations are kept in `RESERVED` and
    are not released."

    Design: Difficulty/transitive_cascade/request_changes_reverts_line_depth2
    """
    ctx = fixtures.setup_in_production_order(
        product_overrides={"base_price_cents": 4000, "standard_lead_days": 3}, on_hand_qty=10
    )
    line, cust_obj = ctx["line"], ctx["customer"]
    cust = make_customer_headers(cust_obj["id"])
    p2 = validate_success(
        api.create_proof(line["id"], factories.create_proof_payload(proof_kind="LOGO", content_ref="logo-v2"), STAFF),
        201,
    )
    validate_success(api.send_proof(line["id"], p2["id"], STAFF))
    validate_success(api.request_changes_proof(line["id"], p2["id"], cust))
    comp = validate_success(api.get_component(ctx["component"]["id"], STAFF))
    # Allocation kept RESERVED -> allocated_qty still reflects the reservation.
    assert comp["allocated_qty"] == 1
    assert comp["on_hand_qty"] == 10


# ─── non_linear_state_machine: parallel production x payment dimensions ───
def test_order_parallel_dimensions_payment_independent_of_production(api):
    """PRD §3.6: "A deposit moves the order `UNPAID → DEPOSIT_PAID`. It is payable only
    after the invoice is locked — that is, the order's `production_status` must be
    `CONFIRMED`, or the payment is rejected with `ERR_INVALID_STATE` — and only while
    `payment_status` is `UNPAID`. Its `amount_cents` must equal `deposit_due_cents` exactly,
    or the payment is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_payment_independent_of_production
    """
    ctx = fixtures.setup_confirmed_order(
        product_overrides={"base_price_cents": 10000, "standard_lead_days": 3}, on_hand_qty=10
    )
    order, cust_obj = ctx["order"], ctx["customer"]
    cust = make_customer_headers(cust_obj["id"])
    assert order["deposit_due_cents"] == 5000
    paid = validate_success(
        api.create_payment(order["id"], factories.create_payment_payload(5000, "DEPOSIT"), cust), 201
    )
    reread = validate_success(api.get_order(order["id"], cust))
    assert reread["payment_status"] == "DEPOSIT_PAID"
    assert reread["production_status"] == "CONFIRMED"
    assert reread["deposit_due_cents"] == 5000
    assert reread["amount_paid_cents"] == 5000


def test_deposit_payment_does_not_advance_production(api):
    """PRD §3.6: "The payment dimension runs in parallel to production and is driven by the
    customer."
    PRD §3.7: "Once a deposit (or full payment) is in hand, staff begin production,
    advancing the order `CONFIRMED → IN_PRODUCTION`."

    Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_payment_independent_of_production
    """
    ctx = fixtures.setup_confirmed_order(
        product_overrides={"base_price_cents": 10000, "standard_lead_days": 3}, on_hand_qty=10
    )
    order, cust_obj = ctx["order"], ctx["customer"]
    cust = make_customer_headers(cust_obj["id"])
    validate_success(
        api.create_payment(order["id"], factories.create_payment_payload(order["deposit_due_cents"], "DEPOSIT"), cust), 201
    )
    # Production status remains CONFIRMED — paying does not itself start production.
    reread = validate_success(api.get_order(order["id"], cust))
    assert reread["production_status"] == "CONFIRMED"
    assert reread["payment_status"] == "DEPOSIT_PAID"


# ─── cross_entity_state_dependency: start-production blocked until deposit ───
def test_start_production_blocked_until_deposit_paid(api):
    """PRD §3.7: "This step requires the order to be in `CONFIRMED` and its `payment_status`
    to be `DEPOSIT_PAID` or `PAID_IN_FULL`; starting production while the order is still
    `UNPAID` is rejected with `ERR_DEPOSIT_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/start_production_blocked_until_deposit_paid
    """
    ctx = fixtures.setup_confirmed_order(
        product_overrides={"base_price_cents": 4000, "standard_lead_days": 3}, on_hand_qty=10
    )
    order, cust_obj = ctx["order"], ctx["customer"]
    cust = make_customer_headers(cust_obj["id"])
    resp = api.start_production(order["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_REQUIRED.value)
    reread = validate_success(api.get_order(order["id"], cust))
    assert reread["production_status"] == "CONFIRMED"
    assert reread["payment_status"] == "UNPAID"


def test_start_production_succeeds_after_deposit(api):
    """PRD §3.7: "Once a deposit (or full payment) is in hand, staff begin production,
    advancing the order `CONFIRMED → IN_PRODUCTION`."
    PRD §3.7: "Starting production flips every `PENDING` line to `line_status` `ALLOCATED` —
    their reserved allocations stay `RESERVED` — and increments the order's `version`."

    Design: Difficulty/cross_entity_state_dependency/start_production_blocked_until_deposit_paid
    """
    ctx = fixtures.setup_confirmed_order(
        product_overrides={"base_price_cents": 4000, "standard_lead_days": 3}, on_hand_qty=10
    )
    order, cust_obj, line = ctx["order"], ctx["customer"], ctx["line"]
    cust = make_customer_headers(cust_obj["id"])
    validate_success(
        api.create_payment(order["id"], factories.create_payment_payload(order["deposit_due_cents"], "DEPOSIT"), cust), 201
    )
    started = validate_success(api.start_production(order["id"], STAFF))
    assert started["production_status"] == "IN_PRODUCTION"
    line_reread = validate_success(api.get_order_line(line["id"], cust))
    assert line_reread["line_status"] == "ALLOCATED"


# ─── Corner: bubble-up with two lines (assemble first keeps IN_PRODUCTION, second -> READY) ───
def _setup_two_line_in_production(api):
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    component = fixtures.create_component(on_hand_qty=20)
    product = fixtures.create_product(
        component["id"], base_price_cents=4000, engraving_price_per_char_cents=0,
        standard_lead_days=3,
    )
    customer = fixtures.register_customer()
    cust = make_customer_headers(customer["id"])
    order = fixtures.create_order(customer)
    l1 = fixtures.add_line(order, customer, product["id"], quantity=1)
    l2 = fixtures.add_line(order, customer, product["id"], quantity=1)
    fixtures.add_approved_proof(l1, customer, content_ref="A")
    fixtures.add_approved_proof(l2, customer, content_ref="B")
    priced = fixtures.price(order, customer)
    confirmed = validate_success(
        api.confirm_order(order["id"], {"expected_order_version": priced["version"]}, cust)
    )
    fixtures.pay(order, customer, confirmed["deposit_due_cents"], "DEPOSIT")
    validate_success(api.start_production(order["id"], STAFF))
    validate_success(api.engrave_line(l1["id"], STAFF))
    validate_success(api.engrave_line(l2["id"], STAFF))
    return order, customer, cust, l1, l2


def test_assemble_first_of_two_keeps_order_in_production(api):
    """PRD §3.7: "When the assembly that finishes a line leaves every line on the order in
    `ASSEMBLED`, the order auto-advances `IN_PRODUCTION → READY`, stamping `ready_at` with
    the current time and incrementing the order's `version`. This system transition fires
    only when the order is `IN_PRODUCTION` and all of its lines are assembled."

    Design: Corner/state_machines/assemble_first_of_two_keeps_order_in_production
    """
    order, customer, cust, l1, l2 = _setup_two_line_in_production(api)
    validate_success(api.assemble_line(l1["id"], STAFF))
    reread = validate_success(api.get_order(order["id"], cust))
    assert reread["production_status"] == "IN_PRODUCTION"
    assert validate_success(api.get_order_line(l1["id"], cust))["line_status"] == "ASSEMBLED"
    assert validate_success(api.get_order_line(l2["id"], cust))["line_status"] == "ENGRAVING"


def test_bubble_up_order_ready_when_all_lines_assembled(api):
    """PRD §3.7: "When the assembly that finishes a line leaves every line on the order in
    `ASSEMBLED`, the order auto-advances `IN_PRODUCTION → READY`, stamping `ready_at` with
    the current time and incrementing the order's `version`."

    Design: Corner/state_machines/bubble_up_order_ready_when_all_lines_assembled
    """
    order, customer, cust, l1, l2 = _setup_two_line_in_production(api)
    validate_success(api.assemble_line(l1["id"], STAFF))
    validate_success(api.assemble_line(l2["id"], STAFF))
    reread = validate_success(api.get_order(order["id"], cust))
    assert reread["production_status"] == "READY"
    assert validate_success(api.get_order_line(l1["id"], cust))["line_status"] == "ASSEMBLED"
    assert validate_success(api.get_order_line(l2["id"], cust))["line_status"] == "ASSEMBLED"


# ─── Corner: receive stock clears low_stock flag ───
def test_receive_stock_clears_low_stock_flag(api):
    """PRD §3.1: "Receiving stock raises `on_hand_qty` by the supplied `received_qty` and
    recomputes the derived figures, bumping the component's `version`."
    PRD §2.9: "A component's `low_stock` flag is true exactly when its `available_qty` is
    less than or equal to its configured `reorder_point`, and false otherwise."

    Design: Corner/cross_cutting_complexity_layers/receive_stock_clears_low_stock_flag
    """
    component = fixtures.create_component(on_hand_qty=0, reorder_point=2)
    assert component["low_stock"] is True
    received = validate_success(
        api.receive_component(component["id"], {"received_qty": 5}, fixtures.MANAGER)
    )
    assert received["on_hand_qty"] == 5
    assert received["available_qty"] == 5
    assert received["low_stock"] is False
