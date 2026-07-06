"""Validation precedence conflicts, cross-entity guards, RBAC, and special orders.

Queue A: priority_pair_validation_conflict/state_beats_fiscal_on_capture,
         priority_pair_validation_conflict/existence_beats_temporal_on_preorder,
         cross_entity_state_dependency/order_ship_requires_payment_paid,
         cross_entity_state_dependency/product_open_preorders_requires_allocation_window.
Queue B: customer_cannot_create_product, customer_cannot_cancel_other_customers_order,
         fulfill_online_order_wrong_channel_returns_invalid_state,
         special_order_cancel_forfeits_deposit.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    TEST_USERS, make_customer_headers,
    register_customer, create_product, create_inventory_item,
    create_rsd_allocation, setup_order_with_items, setup_authorized_order,
    setup_paid_order, open_order, add_line, set_clock, create_special_order,
)

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["store_clerk_headers"]


# ---------------------------------------------------------------------------
# Queue A — state_beats_fiscal_on_capture (>=2 tests)
# ---------------------------------------------------------------------------
def _unpaid_order_never_authorized(api):
    """ONLINE order, one NM line, still UNPAID; buyer has 0 store credit."""
    customer, product, items, order, lines = setup_order_with_items(
        api, channel="ONLINE", base_price_cents=3000, is_used=False, condition_grade="NM",
        num_items=1)
    return customer, order


def test_capture_on_unpaid_order_fails_state_before_fiscal(api):
    """PRD §2.9: "State validity is checked fifth: if the target resource is not in a state
    that permits the requested transition, the request yields ERR_INVALID_STATE (409). ...
    Only after these general gates pass are the operation-specific business rules ... credit
    sufficiency ... evaluated."
    PRD §3.3: "A StoreClerk then captures payment, moving payment_status from AUTHORIZED to PAID."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_capture
    """
    customer, order = _unpaid_order_never_authorized(api)
    resp = api.capture_payment(order["id"], {"credit_applied_cents": 999999}, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_capture_on_unpaid_order_status_409(api):
    """PRD §2.9: "State validity is checked fifth: if the target resource is not in a state
    that permits the requested transition, the request yields ERR_INVALID_STATE (409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_capture
    """
    customer, order = _unpaid_order_never_authorized(api)
    resp = api.capture_payment(order["id"], {"credit_applied_cents": 999999}, CLERK)
    assert resp.status_code == 409, f"expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Queue A — existence_beats_temporal_on_preorder (>=2 tests)
# ---------------------------------------------------------------------------
def _closed_window_pool_clock_past(api):
    buyer = register_customer(api, full_name="PConflict2")
    product, alloc = create_rsd_allocation(
        api, allocation_total=5, window_open_at="2026-03-01T00:00:00Z",
        window_close_at="2026-03-10T00:00:00Z")
    set_clock(api, to_iso8601="2026-03-15T00:00:00Z")
    return buyer, product, alloc


def test_preorder_missing_allocation_fails_existence_before_temporal(api):
    """PRD §2.9: "Existence of all referenced resources is checked third, left to right,
    yielding ERR_NOT_FOUND (404). ... Only after these general gates pass are the
    operation-specific business rules — pre-order windows ... evaluated."
    PRD §2.8: "the product, allocation, inventory item, or consignment a request names
    must exist, or the request is rejected with ERR_NOT_FOUND."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_temporal_on_preorder
    """
    buyer, product, alloc = _closed_window_pool_clock_past(api)
    resp = api.create_preorder({
        "customer_id": buyer["id"], "product_id": product["id"],
        "allocation_id": NON_EXISTENT_UUID,
        "pickup_window_start": "2026-04-01T09:00:00Z", "pickup_window_end": "2026-04-01T17:00:00Z",
        "expected_allocation_version": alloc["version"],
    }, make_customer_headers(buyer["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_preorder_missing_allocation_status_404(api):
    """PRD §2.9: "Existence of all referenced resources is checked third, left to right,
    yielding ERR_NOT_FOUND (404)."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_temporal_on_preorder
    """
    buyer, product, alloc = _closed_window_pool_clock_past(api)
    resp = api.create_preorder({
        "customer_id": buyer["id"], "product_id": product["id"],
        "allocation_id": NON_EXISTENT_UUID,
        "pickup_window_start": "2026-04-01T09:00:00Z", "pickup_window_end": "2026-04-01T17:00:00Z",
        "expected_allocation_version": alloc["version"],
    }, make_customer_headers(buyer["id"]))
    assert resp.status_code == 404, f"expected 404, got {resp.status_code}"


# ---------------------------------------------------------------------------
# Queue A — order_ship_requires_payment_paid (>=2 tests)
# ---------------------------------------------------------------------------
def test_ship_authorized_but_uncaptured_order_rejected(api):
    """PRD §3.4: "For an ONLINE order, a StoreClerk ships it, advancing fulfillment_status
    from RESERVED to SHIPPED; this requires the channel to be ONLINE and the payment_status
    to be PAID. ... attempting either while payment has not settled is rejected with
    ERR_DEPENDENCY_NOT_READY."

    Design: Difficulty/cross_entity_state_dependency/order_ship_requires_payment_paid
    """
    customer, product, items, order, lines = setup_authorized_order(
        api, channel="ONLINE", base_price_cents=3000, is_used=False, condition_grade="NM",
        num_items=1)
    resp = api.ship_order(order["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_DEPENDENCY_NOT_READY.value)


def test_ship_uncaptured_order_leaves_fulfillment_reserved(api):
    """PRD §3.4: "The requirement that payment be PAID before shipping or pickup is a
    cross-entity readiness guard: attempting either while payment has not settled is
    rejected with ERR_DEPENDENCY_NOT_READY."

    Design: Difficulty/cross_entity_state_dependency/order_ship_requires_payment_paid
    """
    customer, product, items, order, lines = setup_authorized_order(
        api, channel="ONLINE", base_price_cents=3000, is_used=False, condition_grade="NM",
        num_items=1)
    validate_error(api.ship_order(order["id"], CLERK),
                   ApiErrorId.ERR_DEPENDENCY_NOT_READY.value)
    data = validate_success(api.get_order(order["id"], make_customer_headers(customer["id"])))
    assert data["fulfillment_status"] == "RESERVED", f"got {data['fulfillment_status']}"


# ---------------------------------------------------------------------------
# Queue A — product_open_preorders_requires_allocation_window (>=2 tests)
# ---------------------------------------------------------------------------
def _listed_rsd_product_window_closed(api):
    product, alloc = create_rsd_allocation(
        api, allocation_total=3, window_open_at="2026-03-01T00:00:00Z",
        window_close_at="2026-03-05T00:00:00Z")
    validate_success(api.list_product(product["id"], MANAGER))
    set_clock(api, to_iso8601="2026-03-10T00:00:00Z")
    return product


def test_open_preorders_past_window_rejected(api):
    """PRD §3.1: "From LISTED, an exclusive product can be opened for pre-orders, advancing
    catalog_status to PRE_ORDER_OPEN; this requires that the product is flagged
    is_rsd_exclusive, that an Allocation exists for it, and that the logical clock has not
    yet reached that allocation's window_close_at." PRD §3.1: "an attempt from the wrong
    starting state is rejected with ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/product_open_preorders_requires_allocation_window
    """
    product = _listed_rsd_product_window_closed(api)
    resp = api.open_preorders(product["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_open_preorders_rejected_leaves_product_listed(api):
    """PRD §3.1: "A product's catalog_status walks a small lifecycle." PRD §3.1: "an attempt
    from the wrong starting state is rejected with ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/product_open_preorders_requires_allocation_window
    """
    product = _listed_rsd_product_window_closed(api)
    validate_error(api.open_preorders(product["id"], MANAGER), ApiErrorId.ERR_INVALID_STATE.value)
    data = validate_success(api.get_product(product["id"], MANAGER))
    assert data["catalog_status"] == "LISTED", f"got {data['catalog_status']}"


# ---------------------------------------------------------------------------
# Queue B — RBAC and special orders
# ---------------------------------------------------------------------------
def test_customer_cannot_create_product(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN (HTTP 403)."

    Design: Corner/rbac/customer_cannot_create_product
    """
    customer = register_customer(api, full_name="RBAC")
    resp = api.create_product(
        {"artist": "X", "title": "Y", "format": "VINYL", "base_price_cents": 1000},
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_customer_cannot_cancel_other_customers_order(api):
    """PRD §2.1: "a Customer may act only on orders, trade-ins, pre-orders, grading disputes,
    and special orders whose customer_id equals their X-User-ID ... An attempt by an
    authenticated Customer to mutate a resource they do not own is rejected with
    ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Design: Corner/rbac/customer_cannot_cancel_other_customers_order
    """
    owner = register_customer(api, full_name="Owner")
    intruder = register_customer(api, full_name="Intruder")
    product = create_product(api, artist="Portishead", title="Dummy", format="CD",
                             base_price_cents=1500)
    item = create_inventory_item(api, product_id=product["id"], is_used=False, condition_grade="NM")
    order = open_order(api, customer=owner, channel="ONLINE")
    add_line(api, order=order, customer=owner, item=item)
    resp = api.cancel_order(order["id"], make_customer_headers(intruder["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_fulfill_online_order_wrong_channel_rejected(api):
    """PRD §3.4: "For an IN_STORE order, a StoreClerk completes an in-store pickup, advancing
    fulfillment_status from RESERVED to PICKED_UP; this requires the channel to be IN_STORE
    and the payment_status to be PAID." PRD §2.9: "State validity is checked fifth: if the
    target resource is not in a state that permits the requested transition, the request
    yields ERR_INVALID_STATE (409)." The channel is an attribute of the target order, so an
    ONLINE order does not permit the in-store pickup transition — and since payment HAS
    settled here, ERR_DEPENDENCY_NOT_READY (which §3.4 scopes to unsettled payment) does not
    apply.

    Design: Corner/state_machines/fulfill_online_order_wrong_channel_returns_invalid_state
    """
    customer, product, items, order, lines = setup_paid_order(
        api, channel="ONLINE", base_price_cents=3000, is_used=False, condition_grade="NM",
        num_items=1)
    resp = api.fulfill_order(order["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_special_order_cancel_forfeits_deposit(api):
    """PRD §3.9: "A Customer may cancel their own special order while it is still REQUESTED
    or SOURCING, moving it to the terminal CANCELLED; in either case the deposit_cents is
    forfeited." PRD §3.9: "The deposit is non-refundable."

    Design: Corner/errors/special_order_cancel_forfeits_deposit
    """
    customer, so = create_special_order(api, description="rare pressing", deposit_cents=500)
    hdr = make_customer_headers(customer["id"])
    data = validate_success(api.cancel_special_order(so["id"], hdr))
    assert data["status"] == "CANCELLED", f"got {data['status']}"
    cust = validate_success(api.get_customer(customer["id"], hdr))
    assert cust["store_credit_cents"] == 0, f"deposit must not be refunded, got {cust['store_credit_cents']}"
