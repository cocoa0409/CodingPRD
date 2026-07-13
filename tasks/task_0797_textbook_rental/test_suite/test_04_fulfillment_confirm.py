"""Fulfilment: copy selection, availability and window gating, validation precedence
at confirm, and inventory conservation. Difficulty instances only."""
from test_helpers import (
    validate_success, validate_error,
    create_catalog_item_payload, create_customer_payload, create_order_payload,
    TEST_USERS, make_customer_headers,
    set_clock, create_catalog_item, create_funded_customer,
    setup_paid_confirmed_rental, setup_inspected_rental,
    get_order, get_rental, get_inventory_unit,
)

ADMIN = TEST_USERS["admin_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]


# ─── Confirm gated by InventoryUnit availability (Order<->InventoryUnit) ─

def test_second_confirm_no_available_unit_error(api):
    """PRD 3.4: "The selector first gathers every `InventoryUnit` of the order's
    `catalog_item_id` whose `status` is `AVAILABLE`. If no such copy exists at all,
    confirmation fails with `ERR_NO_AVAILABLE_UNIT`."

    Design: Difficulty/cross_entity_state_dependency/confirm_gated_by_inventory_unit_availability
    """
    ctx = setup_paid_confirmed_rental(email="cg@x.com")  # the single unit is now RENTED
    order2 = validate_success(api.create_order(
        create_order_payload(ctx["cat"]["id"], "RENT", rental_term_days=90,
                             desired_start_date="2026-03-01T00:00:00Z"), ctx["headers"]), 201)
    validate_success(api.pay_order(order2["id"], ctx["headers"]), 200)
    res = api.confirm_order(order2["id"], WAREHOUSE)
    validate_error(res, "ERR_NO_AVAILABLE_UNIT", expected_status=409)


def test_second_confirm_leaves_order_pending(api):
    """PRD 3.4: "If no such copy exists at all, confirmation fails with
    `ERR_NO_AVAILABLE_UNIT`."

    Design: Difficulty/cross_entity_state_dependency/confirm_gated_by_inventory_unit_availability
    """
    ctx = setup_paid_confirmed_rental(email="cg2@x.com")
    order2 = validate_success(api.create_order(
        create_order_payload(ctx["cat"]["id"], "RENT", rental_term_days=90,
                             desired_start_date="2026-03-01T00:00:00Z"), ctx["headers"]), 201)
    validate_success(api.pay_order(order2["id"], ctx["headers"]), 200)
    api.confirm_order(order2["id"], WAREHOUSE)  # rejected
    assert get_order(order2["id"])["fulfillment_status"] == "PENDING"


# ─── Priority: state (ERR_ORDER_NOT_PAID) beats referential (no unit) ─

def test_confirm_state_beats_no_available_unit(api):
    """PRD 3.4: "it requires the order to be in `PENDING` fulfilment with
    `payment_status` of `PAID`; an order that is not both pending and paid is rejected
    with `ERR_ORDER_NOT_PAID`."
    PRD 2.8: "because state outranks the referential and temporal tiers, a lifecycle
    conflict surfaces before an availability or window check".

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_no_available_unit
    """
    cat = validate_success(api.create_catalog(create_catalog_item_payload(), ADMIN), 201)  # NO units
    cust = validate_success(api.create_customer(create_customer_payload(email="sb@x.com"), ADMIN), 201)
    headers = make_customer_headers(cust["id"])
    order = validate_success(api.create_order(
        create_order_payload(cat["id"], "RENT", rental_term_days=90,
                             desired_start_date="2026-03-01T00:00:00Z"), headers), 201)  # UNPAID
    res = api.confirm_order(order["id"], WAREHOUSE)
    validate_error(res, "ERR_ORDER_NOT_PAID", expected_status=409)


def test_confirm_unpaid_no_unit_leaves_order_unpaid(api):
    """PRD 3.4: "an order that is not both pending and paid is rejected with
    `ERR_ORDER_NOT_PAID`."

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_no_available_unit
    """
    cat = validate_success(api.create_catalog(create_catalog_item_payload(), ADMIN), 201)
    cust = validate_success(api.create_customer(create_customer_payload(email="sb2@x.com"), ADMIN), 201)
    headers = make_customer_headers(cust["id"])
    order = validate_success(api.create_order(
        create_order_payload(cat["id"], "RENT", rental_term_days=90,
                             desired_start_date="2026-03-01T00:00:00Z"), headers), 201)
    api.confirm_order(order["id"], WAREHOUSE)  # rejected
    reread = get_order(order["id"])
    assert reread["payment_status"] == "UNPAID"
    assert reread["fulfillment_status"] == "PENDING"


# ─── Half-open unit window + inspection buffer conflict ───────────────

def test_rerent_inside_buffer_window_conflict(api):
    """PRD 3.4: "A copy is eligible only if it has no existing rental window — each
    existing rental's own window running from its `start_date` up to but not including
    its due date plus the same two-day buffer — that overlaps the requested window under
    this half-open test. If `AVAILABLE` copies exist but every one of them collides on
    the window, confirmation fails with `ERR_UNIT_WINDOW_CONFLICT` — a distinct, temporal
    outcome separate from the case where no available copy exists at all."

    Design: Difficulty/resource_temporal_overlap/unit_rental_window_halfopen_plus_buffer_conflict
    """
    # Rental1 window [2026-03-01, due 2026-05-30 + 2d) persists after an on-time return.
    ctx = setup_inspected_rental(reported_condition="GOOD", inspect_clock="2026-05-30T00:00:00Z",
                                 email="uw@x.com")
    order2 = validate_success(api.create_order(
        create_order_payload(ctx["cat"]["id"], "RENT", rental_term_days=90,
                             desired_start_date="2026-05-31T00:00:00Z"), ctx["headers"]), 201)
    validate_success(api.pay_order(order2["id"], ctx["headers"]), 200)
    res = api.confirm_order(order2["id"], WAREHOUSE)
    validate_error(res, "ERR_UNIT_WINDOW_CONFLICT", expected_status=409)


def test_window_conflict_leaves_second_order_pending(api):
    """PRD 3.4: "If `AVAILABLE` copies exist but every one of them collides on the
    window, confirmation fails with `ERR_UNIT_WINDOW_CONFLICT`".

    Design: Difficulty/resource_temporal_overlap/unit_rental_window_halfopen_plus_buffer_conflict
    """
    ctx = setup_inspected_rental(reported_condition="GOOD", inspect_clock="2026-05-30T00:00:00Z",
                                 email="uw2@x.com")
    order2 = validate_success(api.create_order(
        create_order_payload(ctx["cat"]["id"], "RENT", rental_term_days=90,
                             desired_start_date="2026-05-31T00:00:00Z"), ctx["headers"]), 201)
    validate_success(api.pay_order(order2["id"], ctx["headers"]), 200)
    api.confirm_order(order2["id"], WAREHOUSE)  # rejected
    assert get_order(order2["id"])["fulfillment_status"] == "PENDING"


# ─── Inventory conserved on rent then on-time return ──────────────────

def test_on_time_return_restores_unit_available_and_counts_rental(api):
    """PRD 3.6: "returns the copy's `status` from `IN_INSPECTION` to `AVAILABLE` and
    overwrites its `condition_grade` with the `reported_condition`".
    PRD 3.4: "creates a `Rental` in `ACTIVE` status, and increments the copy's
    `times_rented` by one."

    Design: Difficulty/compensating_invariant/inventory_units_conserved_on_rent_then_return
    """
    ctx = setup_inspected_rental(reported_condition="GOOD", inspect_clock="2026-05-30T00:00:00Z",
                                 email="ic1@x.com")
    unit = get_inventory_unit(ctx["unit"]["id"])
    assert unit["status"] == "AVAILABLE"
    assert unit["times_rented"] == 1, unit["times_rented"]


def test_on_time_return_closes_rental_returned(api):
    """PRD 3.6: "the linked rental is driven from `RETURN_INITIATED` to
    `CLOSED_RETURNED`".

    Design: Difficulty/compensating_invariant/inventory_units_conserved_on_rent_then_return
    """
    ctx = setup_inspected_rental(reported_condition="GOOD", inspect_clock="2026-05-30T00:00:00Z",
                                 email="ic2@x.com")
    assert get_rental(ctx["rental"]["id"])["status"] == "CLOSED_RETURNED"
