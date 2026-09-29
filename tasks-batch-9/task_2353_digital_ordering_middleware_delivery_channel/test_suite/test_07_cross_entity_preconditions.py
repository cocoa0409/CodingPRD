"""Operations whose legality is decided by the state of a neighbouring record.

A dispatch reads the order's register status; a reconciliation reads the review
state of every refund hanging off the orders on the account.
"""
from test_helpers import (
    ANALYST_ONE_USER_ID,
    ApiErrorId,
    accept_adjustment,
    assert_delivery_assignment,
    assert_instant,
    create_adjustment_in_review,
    create_courier_network,
    dispatch_order,
    env_store_headers,
    inject_order,
    make_analyst_headers,
    order_line,
    place_order,
    place_ready_order,
    read_adjustment,
    read_network,
    read_order,
    read_statement,
    reconcile_statement,
    setup_published_store,
    setup_statement_with_orders,
    validate_error,
    validate_paginated,
)

BURGER_LINE = [order_line("BURGER", 1)]


def _marketplace_network():
    return create_courier_network(
        code="N_MKT", network_type="MARKETPLACE", priority_rank=1, per_delivery_fee_cents=300,
        handoff_sla_seconds=600, dispatch_buffer_seconds=120, max_concurrent_assignments=5,
    )


def test_dispatch_is_refused_while_the_register_has_not_taken_the_order(api):
    """A pending order is not yet a kitchen ticket, so there is nothing to hand over.

    PRD: "Four gates precede selection, in this order: the order's
    `fulfillment_status` must be `PREPARING` or `READY`, or the request is
    `ERR_INVALID_ORDER_STATE`; its `injection_status` must be `ACCEPTED` or
    `TABLET_FALLBACK`, or the request is `ERR_ORDER_NOT_INJECTED`".

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_order_injection_accepted
    """
    env = setup_published_store()
    network = _marketplace_network()
    order = place_order(env, external_ref="MP-1001", fulfillment_mode="DELIVERY")
    assert order["injection_status"] == "PENDING"

    response = api.dispatch_order(order["id"], env_store_headers(env))

    validate_error(response, ApiErrorId.ERR_ORDER_NOT_INJECTED, 409)
    _rows, meta = validate_paginated(
        api.list_delivery_assignments(env_store_headers(env), params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 0
    assert read_network(network["id"])["open_assignment_count"] == 0


def test_dispatch_succeeds_once_the_register_has_accepted_the_order(api):
    """Injection is the neighbouring state the dispatch gate was waiting on.

    PRD: "On `OK` the order moves from `PENDING` to `ACCEPTED`". "A new assignment
    records the `order_id` it serves and the `courier_network_id` that won
    selection, starts in `OFFERED` with `offered_at` stamped from the clock, and
    sets `occupancy_until` to `offered_at` advanced by the network's
    `handoff_sla_seconds` and then by its `dispatch_buffer_seconds`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_order_injection_accepted
    """
    env = setup_published_store()
    network = _marketplace_network()
    order = place_order(env, external_ref="MP-1001", fulfillment_mode="DELIVERY")

    injected = inject_order(env, order["id"])
    assert injected["injection_status"] == "ACCEPTED"
    assert injected["fulfillment_status"] == "PREPARING"

    assignment = dispatch_order(env, order["id"])

    assert_delivery_assignment(assignment)
    assert assignment["state"] == "OFFERED"
    assert assignment["order_id"] == order["id"]
    assert assignment["courier_network_id"] == network["id"]
    assert_instant(assignment["offered_at"], "2026-08-03T16:00:00Z", "offered_at")
    assert_instant(assignment["occupancy_until"], "2026-08-03T16:12:00Z", "occupancy_until")
    assert read_network(network["id"])["open_assignment_count"] == 1


def test_reconciliation_is_refused_while_a_refund_is_still_in_review(api):
    """An open refund could still move the tier base, so the account cannot freeze.

    PRD: "its `open_adjustment_count` must be exactly 0, or it is refused with
    `ERR_OPEN_ADJUSTMENTS_PRESENT` — reconciling while a refund is still in review
    would let the tier base move afterwards, which is precisely what a frozen
    statement must not do."

    Design: Difficulty/cross_entity_state_dependency/reconcile_blocked_by_open_adjustment
    """
    env = setup_published_store()
    order = place_ready_order(env, external_ref="MP-1001")
    statement = setup_statement_with_orders(env, [order])
    adjustment = create_adjustment_in_review(read_order(order["id"]), amount_cents=1000)
    assert adjustment["state"] == "CHANNEL_REVIEW"

    before = read_statement(statement["id"])
    assert before["open_adjustment_count"] == 1
    assert before["tier_base_cents"] == 3289
    assert before["commission_cents"] == 822
    assert before["net_payable_cents"] == 2467

    response = api.reconcile_statement(statement["id"], make_analyst_headers())

    validate_error(response, ApiErrorId.ERR_OPEN_ADJUSTMENTS_PRESENT, 409)
    unchanged = read_statement(statement["id"])
    assert unchanged["state"] == "OPEN"
    assert unchanged["reconciled_by_user_id"] is None
    assert unchanged["net_payable_cents"] == 2467


def test_reconciliation_proceeds_once_the_refund_has_been_accepted(api):
    """Settling the review closes the blocker and freezes the reduced figures.

    PRD: "Reconciliation recomputes the aggregates through the pipeline and records
    the acting `X-User-ID` as `reconciled_by_user_id`, overwriting whatever was
    there before when a disputed statement is reconciled a second time." "`ACCEPTED`
    and `REVERSED` are settled outcomes and never block anything."

    Design: Difficulty/cross_entity_state_dependency/reconcile_blocked_by_open_adjustment
    """
    env = setup_published_store()
    order = place_ready_order(env, external_ref="MP-1001")
    statement = setup_statement_with_orders(env, [order])
    adjustment = create_adjustment_in_review(read_order(order["id"]), amount_cents=1000)
    validate_error(
        api.reconcile_statement(statement["id"], make_analyst_headers()),
        ApiErrorId.ERR_OPEN_ADJUSTMENTS_PRESENT, 409,
    )

    accept_adjustment(adjustment)
    assert read_adjustment(adjustment["id"])["state"] == "ACCEPTED"
    assert read_statement(statement["id"])["open_adjustment_count"] == 0

    reconciled = reconcile_statement(statement, analyst_user_id=ANALYST_ONE_USER_ID)

    assert reconciled["state"] == "RECONCILED"
    assert reconciled["reconciled_by_user_id"] == ANALYST_ONE_USER_ID
    assert reconciled["adjustment_total_cents"] == 1000
    assert reconciled["tier_base_cents"] == 2289, (
        f"3289 of sales less the 1000 refund, got {reconciled['tier_base_cents']}"
    )
    assert reconciled["tier"] == "TIER_1"
    assert reconciled["commission_cents"] == 572
    assert reconciled["rebate_cents"] == 0
    assert reconciled["net_payable_cents"] == 1717
