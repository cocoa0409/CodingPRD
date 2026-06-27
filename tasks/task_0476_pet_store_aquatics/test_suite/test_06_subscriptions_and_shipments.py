"""Subscription cycle (pause/resume), run-shipment preconditions, FEFO
allocation, OCC stale-version on run-shipment, and filtered listing."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_customer_headers,
    create_subscription_payload, run_shipment_payload,
    make_store, make_product, make_customer, make_lot,
    setup_stocked_subscription, set_clock,
)

INVMGR = TEST_USERS["inventory_manager_headers"]
CLERK = TEST_USERS["store_clerk_headers"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / pause-resume cycle
# ---------------------------------------------------------------------------
def test_subscription_pause_then_resume_cycle(api):
    """PRD §3.10: "The owning `Customer` may pause an active subscription, moving
    it from `ACTIVE` to `PAUSED` ... They may resume a paused subscription,
    moving it from `PAUSED` back to `ACTIVE` ..., but only if the product's
    `recall_state` is `CLEAR`".

    Design: Difficulty/non_linear_state_machine/subscription_active_pause_resume_cycle
    """
    store = make_store()
    product = make_product()
    customer = make_customer(store["id"])
    ch = make_customer_headers(customer["id"])
    sub = validate_success(
        api.create_subscription(
            create_subscription_payload(customer["id"], product["id"], store["id"]),
            ch,
        ), 201,
    )
    paused = validate_success(api.pause_subscription(sub["id"], ch), 200)
    assert paused["status"] == "PAUSED"
    resumed = validate_success(api.resume_subscription(sub["id"], ch), 200)
    assert resumed["status"] == "ACTIVE"


def test_subscription_resume_returns_to_active_status(api):
    """PRD §3.10: "They may resume a paused subscription, moving it from `PAUSED`
    back to `ACTIVE` (permitted only from `PAUSED`, otherwise
    `ERR_SUBSCRIPTION_STATE_INVALID`)".

    Design: Difficulty/non_linear_state_machine/subscription_active_pause_resume_cycle
    """
    store = make_store()
    product = make_product()
    customer = make_customer(store["id"])
    ch = make_customer_headers(customer["id"])
    sub = validate_success(
        api.create_subscription(
            create_subscription_payload(customer["id"], product["id"], store["id"]),
            ch,
        ), 201,
    )
    api.pause_subscription(sub["id"], ch)
    resumed = validate_success(api.resume_subscription(sub["id"], ch), 200)
    assert resumed["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Corner: state_machines / initial state + invalid transition
# ---------------------------------------------------------------------------
def test_subscription_initial_state_active(api):
    """PRD §3.10: "A new subscription is `ACTIVE` with `shipments_count` at
    zero; its `status` takes one of `ACTIVE`, `PAUSED`, `HALTED`, or
    `CANCELLED`".

    Design: Corner/state_machines/subscription_initial_state_active
    """
    store = make_store()
    product = make_product()
    customer = make_customer(store["id"])
    sub = validate_success(
        api.create_subscription(
            create_subscription_payload(customer["id"], product["id"], store["id"]),
            make_customer_headers(customer["id"]),
        ), 201,
    )
    assert sub["status"] == "ACTIVE"
    assert sub["shipments_count"] == 0


def test_cancel_already_cancelled_subscription_returns_invalid_state(api):
    """PRD §3.10: "A new subscription is `ACTIVE` ...; its `status` takes one of
    `ACTIVE`, `PAUSED`, `HALTED`, or `CANCELLED`, with `CANCELLED` terminal."
    PRD §3.10: "The owning `Customer` may cancel from any of `ACTIVE`, `PAUSED`,
    or `HALTED` (otherwise `ERR_SUBSCRIPTION_STATE_INVALID`)".

    Design: Corner/state_machines/cancel_already_cancelled_subscription_returns_invalid_state
    """
    store = make_store()
    product = make_product()
    customer = make_customer(store["id"])
    ch = make_customer_headers(customer["id"])
    sub = validate_success(
        api.create_subscription(
            create_subscription_payload(customer["id"], product["id"], store["id"]),
            ch,
        ), 201,
    )
    validate_success(api.cancel_subscription(sub["id"], ch), 200)
    res = api.cancel_subscription(sub["id"], ch)
    validate_error(res, ApiErrorId.ERR_SUBSCRIPTION_STATE_INVALID)


# ---------------------------------------------------------------------------
# Corner: state_machines / run-shipment before due
# ---------------------------------------------------------------------------
def test_run_shipment_before_due_rejected(api):
    """PRD §3.10: "the logical clock has reached at least `next_ship_at`
    (otherwise `ERR_SHIPMENT_NOT_DUE`)".

    Design: Corner/state_machines/run_shipment_before_due_rejected
    """
    store = make_store()
    product = make_product()
    make_lot(store["id"], product["id"], quantity_on_hand=50)
    customer = make_customer(store["id"])
    sub = validate_success(
        api.create_subscription(
            create_subscription_payload(
                customer["id"], product["id"], store["id"],
                next_ship_at="2026-03-01T00:00:00Z",
            ), CLERK,
        ), 201,
    )
    # Clock at default 2026-01-01, before next_ship_at.
    res = api.run_shipment(sub["id"], run_shipment_payload(sub["version"]), CLERK)
    validate_error(res, ApiErrorId.ERR_SHIPMENT_NOT_DUE)


# ---------------------------------------------------------------------------
# Corner: calculations / FEFO allocation
# ---------------------------------------------------------------------------
def test_fefo_allocation_draws_earliest_expiry_first(api):
    """PRD §2.9: "Candidate lots are ordered by `expiry_date` ascending (earliest
    expiry first) ... Units are taken greedily from the head of this ordered list
    until the requested count is satisfied, and the last lot drawn may be drawn
    partially."
    PRD §3.10: "decrementing each drawn lot's `quantity_on_hand` and marking any
    lot driven to zero as `DEPLETED`".

    Design: Corner/calculations/fefo_allocation_draws_earliest_expiry_first
    """
    store = make_store()
    product = make_product()
    lot_a = make_lot(
        store["id"], product["id"], quantity_on_hand=2, lot_code="A",
        expiry_date="2026-06-01T00:00:00Z",
    )
    lot_b = make_lot(
        store["id"], product["id"], quantity_on_hand=5, lot_code="B",
        expiry_date="2026-12-01T00:00:00Z",
    )
    customer = make_customer(store["id"])
    set_clock("2026-02-02T00:00:00Z")
    sub = validate_success(
        api.create_subscription(
            create_subscription_payload(
                customer["id"], product["id"], store["id"],
                quantity_per_cycle=3, next_ship_at="2026-02-01T00:00:00Z",
            ), CLERK,
        ), 201,
    )
    validate_success(
        api.run_shipment(sub["id"], run_shipment_payload(sub["version"]), CLERK),
        201,
    )
    a_after = validate_success(api.get_inventory_lot(lot_a["id"], INVMGR), 200)
    b_after = validate_success(api.get_inventory_lot(lot_b["id"], INVMGR), 200)
    # Earlier-expiry lot A fully drawn (→0, DEPLETED); lot B drops by remainder.
    assert a_after["quantity_on_hand"] == 0
    assert a_after["status"] == "DEPLETED"
    assert b_after["quantity_on_hand"] == 4


# ---------------------------------------------------------------------------
# Corner: errors / stale subscription version on run-shipment
# ---------------------------------------------------------------------------
def test_stale_subscription_version_on_run_shipment_error(api):
    """PRD §2.10: "A request to run a subscription's due auto-ship cycle must
    carry `expected_subscription_version` matching the target subscription's
    current `version`. If another writer has already advanced the subscription's
    version since the client last read it ... the run is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_subscription_version_on_run_shipment_error
    """
    ctx = setup_stocked_subscription(quantity_per_cycle=1, lot_qty=10)
    sub = ctx["subscription"]
    stale_version = sub["version"]
    # First run fulfills the cycle and bumps the subscription's version.
    validate_success(
        api.run_shipment(sub["id"], run_shipment_payload(stale_version), CLERK),
        201,
    )
    # Second run carries the now-stale original version.
    res = api.run_shipment(sub["id"], run_shipment_payload(stale_version), CLERK)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)


# ---------------------------------------------------------------------------
# Corner: endpoints / filtered listing by customer
# ---------------------------------------------------------------------------
def test_filtered_list_subscriptions_by_customer(api):
    """PRD §3.13: "list endpoints accept the pagination parameters of §2.3 and,
    where noted in §4, optional filter parameters that narrow results by a
    foreign key — for example ... listing subscriptions by `customer_id`,
    `product_id`, or `store_id`".

    Design: Corner/endpoints/filtered_list_subscriptions_by_customer
    """
    store = make_store()
    product = make_product()
    c1 = make_customer(store["id"], email="c1@x.com")
    c2 = make_customer(store["id"], email="c2@x.com")
    validate_success(
        api.create_subscription(
            create_subscription_payload(c1["id"], product["id"], store["id"]),
            make_customer_headers(c1["id"]),
        ), 201,
    )
    validate_success(
        api.create_subscription(
            create_subscription_payload(c2["id"], product["id"], store["id"]),
            make_customer_headers(c2["id"]),
        ), 201,
    )
    res = api.list_subscriptions(CLERK, params={"customer_id": c1["id"]})
    data = validate_success(res, 200)
    assert len(data) == 1
    assert data[0]["customer_id"] == c1["id"]
