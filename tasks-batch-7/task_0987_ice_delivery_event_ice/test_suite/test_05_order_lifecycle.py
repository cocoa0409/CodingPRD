"""Order state machine, will-call lifecycle, and parallel billing dimension
(PRD §2.6, §3.4-§3.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    agent,
    confirm,
    full_book_payload,
    generate_invoice,
    get_depot,
    get_order,
    get_success_data,
    issue_invoice,
    make_active_book,
    make_customer,
    make_customer_agent_headers,
    make_depot,
    make_order,
    make_slot,
    mini_book_payload,
    order_line,
    order_payload,
    picked_up_order,
    quote,
    quoted_order,
    ready_order,
    reserve,
    run_ops,
    set_logical_clock,
    stage,
    staged_order,
    mark_ready,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DEPOT_MGR = TEST_USERS["depot_manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
CLERK_1 = TEST_USERS["billing_clerk_1_headers"]
CLERK_2 = TEST_USERS["billing_clerk_2_headers"]


def _mini_setup(customer_name="Bar", depot_name="Depot", limit=200000):
    depot = make_depot(10, depot_name)
    set_logical_clock()
    make_active_book(mini_book_payload())
    cust = make_customer(
        account_name=customer_name, kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=limit,
    )
    return depot, cust


def test_quote_from_quoted_rejected(api):
    """PRD §3.4: "Quoting requires `DRAFT` and repricing requires `QUOTED`;
    attempting either from another state is rejected as `ERR_INVALID_STATE`."

    Design: Corner/state_machines/quote_from_quoted_rejected
    """
    _depot, cust = _mini_setup("S7", "Depot S7")
    order = quoted_order(
        cust["id"], _depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )
    resp = api.quote_order(order["id"], agent(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_quote_without_active_book_rejected(api):
    """PRD §3.4: "An `ACTIVE` price book must exist at that moment, else
    `ERR_PRICE_BOOK_NOT_ACTIVE`."
    PRD §3.1: "A book is `SCHEDULED` until its `effective_from` reaches the
    logical clock".

    Design: Corner/validations/quote_without_active_book_rejected
    """
    depot = make_depot(10, "Depot V35")
    set_logical_clock()
    book = get_success_data(
        api.create_price_book(
            mini_book_payload(effective_from="2026-06-01T00:00:00Z"), ADMIN
        )
    )
    assert book["status"] == "SCHEDULED", "effective_from lies in the future"
    cust = make_customer(
        account_name="V35", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=200000,
    )
    order = make_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )
    resp = api.quote_order(order["id"], agent(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_PRICE_BOOK_NOT_ACTIVE)


def test_cancel_cancelled_terminal(api):
    """PRD §2.6: "the target must not be in a terminal state for the attempted
    operation: a `CANCELLED` order, a `TERMINATED` route, a `VOID` invoice —
    or a `PAID` one, for issuance — a `CLOSED` slot, a `RELEASED` or `EXPIRED`
    hold, a `COMPLETED` or `CANCELLED` run, a `PROMOTED`, `WITHDRAWN`, or
    `EXPIRED` waitlist entry, or an `EXPIRED` certification, else
    `ERR_ALREADY_TERMINAL` (HTTP 409)."

    Design: Corner/state_machines/cancel_cancelled_terminal
    """
    depot = make_depot(10, "Depot S8")
    cust = make_customer(
        account_name="S8", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=200000,
    )
    order = make_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )
    cancelled = validate_success(api.cancel_order(order["id"], agent(cust["id"])))
    assert cancelled["fulfillment_status"] == "CANCELLED"
    resp = api.cancel_order(order["id"], agent(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


def test_stage_before_confirm_rejected(api):
    """PRD §3.6: "Staging is a `DepotManager` action that moves the order from
    `CONFIRMED` to `STAGED` and requires a `RESERVED` hold for the order to
    exist (`ERR_INVALID_STATE` otherwise)."

    Design: Corner/state_machines/stage_before_confirm_rejected
    """
    depot, cust = _mini_setup("S9", "Depot S9")
    order = quoted_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )
    resp = api.stage_order(order["id"], DEPOT_MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_pickup_before_ready_rejected(api):
    """PRD §2.6: "quoting needs `DRAFT`; confirming needs `QUOTED`; staging
    needs `CONFIRMED`; marking ready needs a `STAGED` will-call order;
    confirming pickup needs `READY_FOR_PICKUP`".

    Design: Corner/state_machines/pickup_before_ready_rejected
    """
    depot, cust = _mini_setup("S10", "Depot S10")
    order = staged_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )
    resp = api.confirm_pickup(order["id"], agent(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_reserve_slot_on_will_call_rejected(api):
    """PRD §3.5: "the order's channel must be `DELIVERY` — will-call orders
    have no slot — and it must not already hold a reservation, since
    re-reservation requires cancelling first (both `ERR_INVALID_STATE`)."

    Design: Corner/validations/reserve_slot_on_will_call_rejected
    """
    depot, cust = _mini_setup("V39", "Depot V39")
    slot = make_slot(depot["id"], date="2026-05-12", capacity_pallets=5)
    order = quoted_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-12",
        window_start="10:00", window_end="12:00",
    )
    resp = api.reserve_slot(
        order["id"], {"delivery_slot_id": slot["id"]}, agent(cust["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_event_too_soon_at_creation(api):
    """PRD §2.4: "At startup the clock reads exactly 2026-05-01T00:00:00Z;
    before any administrative intervention it continues to read that default,
    and it never falls back to wall-clock time."
    PRD §3.4: "The event date must fall at least one day after the current
    logical date — an order for today is too soon and is rejected with
    `ERR_EVENT_TOO_SOON`".

    Design: Corner/validations/event_too_soon_at_creation
    """
    depot = make_depot(10, "Depot V31")
    cust = make_customer(
        account_name="V31", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=100000,
    )
    # No clock call: the startup default makes 2026-05-01 "today".
    payload = order_payload(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-01",
        window_start="10:00", window_end="12:00",
    )
    resp = api.create_order(payload, make_customer_agent_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_EVENT_TOO_SOON)


def test_zero_quantity_line_rejected(api):
    """PRD §3.4: "each line declares a `product_form` of `BLOCK`, `CUBE`, or
    `DRY_ICE`, a `packaging` of `BAG` or `PALLET`, and a `quantity_units` of at
    least one (`ERR_LINE_QUANTITY_INVALID`)."

    Design: Corner/validations/zero_quantity_line_rejected
    """
    depot = make_depot(10, "Depot V32")
    set_logical_clock()
    cust = make_customer(
        account_name="V32", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=100000,
    )
    payload = order_payload(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 0)],
        channel="WILL_CALL", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )
    resp = api.create_order(payload, make_customer_agent_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_LINE_QUANTITY_INVALID)


def test_cancel_quoted_releases_slot(api):
    """PRD §3.6: "From `QUOTED`, a held slot reservation is released:
    `delivery_slot_id` clears, the slot's reserved total drops by the order's
    pallets, and a `FULL` slot can reopen to `OPEN`."

    Design: Corner/state_machines/cancel_quoted_releases_slot
    """
    depot, cust = _mini_setup("S11", "Depot S11")
    slot = make_slot(depot["id"], date="2026-05-12", capacity_pallets=1)
    order = quoted_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="DELIVERY", event_date="2026-05-12",
        window_start="09:00", window_end="11:00",
    )
    reserve(order["id"], cust["id"], slot["id"])

    cancelled = validate_success(api.cancel_order(order["id"], agent(cust["id"])))
    assert cancelled["fulfillment_status"] == "CANCELLED"

    slots, _meta = validate_paginated(
        api.list_delivery_slots(depot["id"], DISPATCHER, params={"date": "2026-05-12"})
    )
    assert slots[0]["reserved_pallets"] == 0
    assert slots[0]["status"] == "OPEN", "FULL -> OPEN on release"

    order_after = get_order(order["id"], agent(cust["id"]))
    assert order_after["delivery_slot_id"] is None


def test_will_call_no_show_sweep(api):
    """PRD §3.7: "when the ops-run checkpoint finds a will-call order still
    `READY_FOR_PICKUP` with the logical clock past its hold's `interval_end`,
    the order moves to `NO_SHOW` and the hold to `EXPIRED`, again with depot
    recompute and promotion-on-easing, and `fulfilled_at` is stamped — a
    no-show remains billable."

    Design: Corner/state_machines/will_call_no_show_sweep
    """
    depot, cust = _mini_setup("S12", "Depot S12")
    order = ready_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-03",
        window_start="10:00", window_end="12:00",
    )
    set_logical_clock("2026-05-04T09:00:00Z")
    ops = run_ops(depot["id"])
    assert order["id"] in ops["no_show_order_ids"]
    assert len(ops["expired_hold_ids"]) == 1

    order_after = get_order(order["id"], ADMIN)
    assert order_after["fulfillment_status"] == "NO_SHOW"
    assert order_after["fulfilled_at"] is not None

    depot_after = get_depot(depot["id"])
    assert depot_after["freezer_free_pallets"] == 10, (
        "the EXPIRED hold released its pallet"
    )


def test_pickup_after_window_expired(api):
    """PRD §3.7: "The pickup itself belongs to the customer: the owning
    `CustomerAgent` confirms it (any other agent is `ERR_FORBIDDEN`), and only
    while the logical clock has not passed the hold's `interval_end`
    (`ERR_PICKUP_WINDOW_EXPIRED`)."

    Design: Corner/errors/pickup_after_window_expired
    """
    depot, cust = _mini_setup("E49", "Depot E49")
    order = ready_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-03",
        window_start="10:00", window_end="12:00",
    )
    set_logical_clock("2026-05-04T09:00:00Z")
    resp = api.confirm_pickup(order["id"], agent(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_PICKUP_WINDOW_EXPIRED)

    order_after = get_order(order["id"], ADMIN)
    assert order_after["fulfillment_status"] == "READY_FOR_PICKUP", (
        "no ops sweep ran: the order has not been swept to NO_SHOW"
    )


# ----------------- difficulty: parallel fulfillment/billing dimensions --------

def test_invoice_void_reverts_billing_while_fulfillment_stays(api):
    """PRD §3.4: "the billing dimension moves only through the invoice attach,
    void, and payment cascades of §3.8. Transitions on one dimension never
    require a particular value of the other except where this document states
    one."
    PRD §3.8: "every attached order reverts from `INVOICED` to `UNBILLED` with
    its `invoice_id` cleared — becoming invoice-eligible again".

    Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_billing_revert
    """
    depot = make_depot(10, "Depot SM1")
    set_logical_clock()
    make_active_book(full_book_payload())
    cust = make_customer(
        account_name="SM1 Bar", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=200000,
    )
    order = picked_up_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 2)],
        channel="WILL_CALL", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )
    assert order["fulfillment_status"] == "PICKED_UP"
    assert order["billing_status"] == "UNBILLED", "dimensions independent"

    invoice = generate_invoice(cust["id"], "2026-05-01", "2026-06-01", CLERK_1)
    assert invoice["total_cents"] == 45000
    assert invoice["status"] == "DRAFT", "generation lands on DRAFT"
    issue_invoice(invoice["id"], CLERK_1)

    # A different clerk voids (segregation of duties, PRD §3.8).
    validate_success(api.void_invoice(invoice["id"], CLERK_2))

    order_after = get_order(order["id"], agent(cust["id"]))
    assert order_after["fulfillment_status"] == "PICKED_UP", (
        "fulfillment untouched by the billing cycle"
    )
    assert order_after["billing_status"] == "UNBILLED", (
        "billing cycled INVOICED -> UNBILLED"
    )
    assert order_after["invoice_id"] is None, "invoice-eligible again"


def test_invoice_attach_moves_only_billing_dimension(api):
    """PRD §3.8: "Each attached order moves from `UNBILLED` to `INVOICED`, has
    its `invoice_id` set, and its `version` incremented."
    PRD §3.4: "Transitions on one dimension never require a particular value
    of the other except where this document states one."

    Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_billing_revert
    """
    depot = make_depot(10, "Depot SM1b")
    set_logical_clock()
    make_active_book(full_book_payload())
    cust = make_customer(
        account_name="SM1b Bar", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=200000,
    )
    order = picked_up_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 2)],
        channel="WILL_CALL", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )
    invoice = generate_invoice(cust["id"], "2026-05-01", "2026-06-01", CLERK_1)

    order_after = get_order(order["id"], agent(cust["id"]))
    assert order_after["fulfillment_status"] == "PICKED_UP", (
        "invoice attach does not touch fulfillment"
    )
    assert order_after["billing_status"] == "INVOICED"
    assert order_after["invoice_id"] == invoice["id"]
