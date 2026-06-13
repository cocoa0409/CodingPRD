"""Order submission validations: cutoff boundary, empty order, delivery-day, cutoff-passed,
delivery-gap buffer, and the customer-credit-hold cross-entity block.

Covers difficulty boundary_precision_check, resource_temporal_overlap (delivery gap),
cross_entity_state_dependency (submit blocked by hold), plus corner validations.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    setup_catalog, set_clock, create_order, add_line, create_draft_order_with_line,
    TEST_USERS,
)

SALES = TEST_USERS["sales_rep_headers"]
CREDIT = TEST_USERS["credit_manager_headers"]


def test_submit_at_exact_cutoff_boundary_passes(api):
    """PRD §3.3: "the distributor's `current_utc` must be at or before the delivery date's
    midnight minus the route's `cutoff_lead_hours` — equality is allowed, and a
    `current_utc` strictly after that moment is rejected with `ERR_CUTOFF_PASSED`."

    Route cutoff_lead_hours 24, delivery 2026-06-17 -> boundary 2026-06-16T00:00:00Z.
    Clock set to exactly the boundary: submit succeeds (the `<=` equality case).

    Design: Difficulty/boundary_precision_check/cutoff_boundary_equal_passes_on_submit
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=12, credit_limit_cents=100000)
    order, _ = create_draft_order_with_line(
        cat["customer"]["id"], cat["product"]["id"], uom="CASE", ordered_qty=1)
    set_clock(cat["distributor"]["id"], "2026-06-16T00:00:00Z")

    submitted = validate_success(api.submit_order(order["id"], SALES), 200)
    assert submitted["fulfillment_status"] == "SUBMITTED"


def test_submit_one_second_before_cutoff_boundary_passes(api):
    """PRD §3.3: "the distributor's `current_utc` must be at or before the delivery date's
    midnight minus the route's `cutoff_lead_hours` — equality is allowed, and a
    `current_utc` strictly after that moment is rejected with `ERR_CUTOFF_PASSED`."

    Second test of the cutoff boundary, one second below the boundary
    (2026-06-15T23:59:59Z < 2026-06-16T00:00:00Z): submit succeeds (the strictly-before
    side of the `<=` boundary).

    Design: Difficulty/boundary_precision_check/cutoff_boundary_equal_passes_on_submit
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=12, credit_limit_cents=100000)
    order, _ = create_draft_order_with_line(
        cat["customer"]["id"], cat["product"]["id"], uom="CASE", ordered_qty=1)
    set_clock(cat["distributor"]["id"], "2026-06-15T23:59:59Z")

    submitted = validate_success(api.submit_order(order["id"], SALES), 200)
    assert submitted["fulfillment_status"] == "SUBMITTED"


def test_submit_one_second_after_cutoff_rejected(api):
    """PRD §3.3: "the distributor's `current_utc` must be at or before the delivery date's
    midnight minus the route's `cutoff_lead_hours` — equality is allowed, and a
    `current_utc` strictly after that moment is rejected with `ERR_CUTOFF_PASSED`."

    Boundary 2026-06-16T00:00:00Z; clock at 2026-06-16T00:00:01Z (strictly after) rejects
    submit with ERR_CUTOFF_PASSED — the strict side of the `<=` boundary.

    Design: Corner/validations/submit_after_cutoff_rejected
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=12, credit_limit_cents=100000)
    order, _ = create_draft_order_with_line(
        cat["customer"]["id"], cat["product"]["id"], uom="CASE", ordered_qty=1)
    set_clock(cat["distributor"]["id"], "2026-06-16T00:00:01Z")

    res = api.submit_order(order["id"], SALES)
    validate_error(res, "ERR_CUTOFF_PASSED")


def test_submit_empty_order_rejected(api):
    """PRD §3.3: "The order must contain at least one `OrderLine` whose `line_status` is
    not `REMOVED`, or it is rejected with `ERR_EMPTY_ORDER`."
    PRD §3.3: "removal sets that line's `line_status` to `REMOVED`."

    An order whose only line was removed (zero non-removed lines) is rejected with
    ERR_EMPTY_ORDER on submit.

    Design: Difficulty/boundary_precision_check/empty_order_submit_zero_lines_rejected
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=12, credit_limit_cents=100000)
    order, line = create_draft_order_with_line(
        cat["customer"]["id"], cat["product"]["id"], uom="CASE", ordered_qty=1)
    validate_success(api.remove_order_line(line["id"], SALES), 200)

    res = api.submit_order(order["id"], SALES)
    validate_error(res, "ERR_EMPTY_ORDER")


def test_submit_order_with_zero_lines_at_all_rejected(api):
    """PRD §3.3: "The order must contain at least one `OrderLine` whose `line_status` is
    not `REMOVED`, or it is rejected with `ERR_EMPTY_ORDER`."

    Second test of the empty-order edge: an order to which no line was ever added is also
    rejected with ERR_EMPTY_ORDER on submit (cardinality-0 non-removed set).

    Design: Difficulty/boundary_precision_check/empty_order_submit_zero_lines_rejected
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=12, credit_limit_cents=100000)
    order = create_order(cat["customer"]["id"])

    res = api.submit_order(order["id"], SALES)
    validate_error(res, "ERR_EMPTY_ORDER")


def test_submit_wrong_delivery_day_rejected(api):
    """PRD §3.3: "The day of week of `requested_delivery_date` must equal the route's
    `delivery_dow`, or the order is rejected with `ERR_DELIVERY_DAY_MISMATCH`."

    Route delivers on Wednesday (dow 2); an order with requested_delivery_date 2026-06-16
    (Tuesday) is rejected ERR_DELIVERY_DAY_MISMATCH (409).

    Design: Corner/validations/submit_wrong_delivery_day_rejected
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=12, credit_limit_cents=100000,
                        clock="2026-06-14T12:00:00Z")
    order = create_order(cat["customer"]["id"], delivery_date="2026-06-16T00:00:00Z")
    add_line(order["id"], cat["product"]["id"], "CASE", 1)

    res = api.submit_order(order["id"], SALES)
    validate_error(res, "ERR_DELIVERY_DAY_MISMATCH")


def test_submit_delivery_gap_buffer_conflict_rejected(api):
    """PRD §3.3: "if the route carries a `min_delivery_gap_days`, then no other order for
    the same customer whose `fulfillment_status` is `SUBMITTED`, `PICKING`, `LOADED`, or
    `DELIVERED` may have a `requested_delivery_date` whose whole-day distance from this
    order's date is less than `min_delivery_gap_days`; a collision is rejected with
    `ERR_DELIVERY_GAP_CONFLICT`."

    With min_delivery_gap_days=10, a second order delivering 2026-06-24 (7 days from an
    existing active order delivering 2026-06-17) collides since 7 < 10.

    Design: Difficulty/resource_temporal_overlap/route_delivery_gap_buffer_conflict
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=24, credit_limit_cents=100000,
                        min_delivery_gap_days=10)
    # Order A delivers 2026-06-17 (Wed), submitted (active).
    order_a, _ = create_draft_order_with_line(
        cat["customer"]["id"], cat["product"]["id"], uom="CASE", ordered_qty=1,
        delivery_date="2026-06-17T00:00:00Z")
    validate_success(api.submit_order(order_a["id"], SALES), 200)

    # Order B delivers 2026-06-24 (next Wed, 7 days later) -> conflict.
    order_b, _ = create_draft_order_with_line(
        cat["customer"]["id"], cat["product"]["id"], uom="CASE", ordered_qty=1,
        delivery_date="2026-06-24T00:00:00Z")
    res = api.submit_order(order_b["id"], SALES)
    validate_error(res, "ERR_DELIVERY_GAP_CONFLICT")


def test_submit_delivery_gap_second_quantity_conflict(api):
    """PRD §3.3: "no other order for the same customer whose `fulfillment_status` is
    `SUBMITTED`, `PICKING`, `LOADED`, or `DELIVERED` may have a `requested_delivery_date`
    whose whole-day distance from this order's date is less than `min_delivery_gap_days`;
    a collision is rejected with `ERR_DELIVERY_GAP_CONFLICT`."

    Second test of the delivery-gap buffer with a tighter window: min_delivery_gap_days=14,
    an existing active order delivering 2026-06-17 collides with a new 2026-06-24 order
    (7 days < 14).

    Design: Difficulty/resource_temporal_overlap/route_delivery_gap_buffer_conflict
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=24, credit_limit_cents=100000,
                        min_delivery_gap_days=14)
    order_a, _ = create_draft_order_with_line(
        cat["customer"]["id"], cat["product"]["id"], uom="CASE", ordered_qty=1,
        delivery_date="2026-06-17T00:00:00Z")
    validate_success(api.submit_order(order_a["id"], SALES), 200)

    order_b, _ = create_draft_order_with_line(
        cat["customer"]["id"], cat["product"]["id"], uom="CASE", ordered_qty=1,
        delivery_date="2026-06-24T00:00:00Z")
    res = api.submit_order(order_b["id"], SALES)
    validate_error(res, "ERR_DELIVERY_GAP_CONFLICT")


def test_submit_blocked_when_customer_on_credit_hold(api):
    """PRD §3.3: "The customer's `ar_status` must be `ACTIVE`; a customer on `CREDIT_HOLD`
    causes `ERR_CUSTOMER_ON_CREDIT_HOLD`."
    PRD §3.5: "A `CreditManager` may place an `ACTIVE` customer on a manual credit hold,
    moving `ar_status` from `ACTIVE` to `CREDIT_HOLD`."

    With the customer manually on CREDIT_HOLD, submitting an otherwise-submittable order
    fails ERR_CUSTOMER_ON_CREDIT_HOLD.

    Design: Difficulty/cross_entity_state_dependency/order_submit_blocked_by_customer_credit_hold
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=12, credit_limit_cents=100000)
    order, _ = create_draft_order_with_line(
        cat["customer"]["id"], cat["product"]["id"], uom="CASE", ordered_qty=1)
    validate_success(api.credit_hold(cat["customer"]["id"], CREDIT), 200)

    res = api.submit_order(order["id"], SALES)
    validate_error(res, "ERR_CUSTOMER_ON_CREDIT_HOLD")


def test_submit_blocked_by_credit_hold_second_scenario(api):
    """PRD §3.3: "The customer's `ar_status` must be `ACTIVE`; a customer on `CREDIT_HOLD`
    causes `ERR_CUSTOMER_ON_CREDIT_HOLD`."
    PRD §3.5: "A hold blocks new order submission and credit approval for that customer."

    Second test of the Order->Customer dependency: a multi-line order is likewise blocked
    from submission while the customer is on CREDIT_HOLD.

    Design: Difficulty/cross_entity_state_dependency/order_submit_blocked_by_customer_credit_hold
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=36, credit_limit_cents=100000)
    order = create_order(cat["customer"]["id"])
    add_line(order["id"], cat["product"]["id"], "CASE", 1)
    add_line(order["id"], cat["product"]["id"], "CASE", 2)
    validate_success(api.credit_hold(cat["customer"]["id"], CREDIT), 200)

    res = api.submit_order(order["id"], SALES)
    validate_error(res, "ERR_CUSTOMER_ON_CREDIT_HOLD")
