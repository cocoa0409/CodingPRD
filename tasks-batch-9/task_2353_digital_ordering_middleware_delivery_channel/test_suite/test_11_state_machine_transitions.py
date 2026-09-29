"""Transitions that are legal, transitions that are refused, and terminal states.

A catalogue is frozen once and never again; an order is made ready once; a
declined offer never becomes an accepted one. Two of these also walk states that
are reached indirectly — a menu version bubbling on its children's availability,
and a statement unwinding itself when the partner disputes it.
"""
from test_helpers import (
    ApiErrorId,
    add_menu_item,
    assert_delivery_assignment,
    assert_instant,
    assert_menu_version,
    assert_pos_injection_attempt,
    assert_remittance_statement,
    assert_store_counters,
    burger_item_payload,
    create_courier_network,
    create_menu_version,
    decline_assignment,
    dispatch_order,
    dispute_statement,
    finalize_menu_version,
    fries_item_payload,
    inject_order,
    listing_for,
    make_admin_headers,
    make_analyst_headers,
    make_courier_agent_headers,
    order_line,
    place_injected_order,
    place_order,
    place_ready_order,
    read_assignment,
    read_menu_version,
    read_network,
    read_order,
    read_statement,
    read_store,
    record_availability_event,
    setup_published_store,
    setup_reconciled_statement,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

BURGER_ONLY = {"item_payloads": [burger_item_payload()]}
BURGER_LINE = [order_line("BURGER", 1)]
PICKUP_BURGER = {"fulfillment_mode": "PICKUP", "lines": BURGER_LINE, "tip_cents": 0}


def test_a_new_menu_version_is_a_draft_that_freezing_turns_into_a_catalogue(api):
    """The version is authored empty, grows an item, and only then becomes publishable.

    PRD: "A fresh version begins in `DRAFT` with `item_count` at 0,
    `published_store_count` at 0, and both `published_at` and `superseded_at` null."
    "Every accepted item increments the version's `item_count`." "Freezing a draft
    moves it from `DRAFT` to `PUBLISHED` and stamps `published_at` with the logical
    clock."

    Design: Corner/state_machines/state_menu_version_initial_state_is_draft
    """
    set_clock()

    version = create_menu_version()

    assert_menu_version(version)
    assert version["state"] == "DRAFT"
    assert version["item_count"] == 0
    assert version["published_store_count"] == 0
    assert version["published_at"] is None
    assert version["superseded_at"] is None

    add_menu_item(version["id"], burger_item_payload())
    with_item = read_menu_version(version["id"])
    assert with_item["item_count"] == 1
    assert with_item["state"] == "DRAFT", "adding an item does not freeze the version"

    frozen = finalize_menu_version(version["id"])
    assert frozen["state"] == "PUBLISHED"
    assert frozen["item_count"] == 1
    assert_instant(frozen["published_at"], "2026-08-03T16:00:00Z", "published_at")


def test_a_frozen_catalogue_refuses_both_a_second_freeze_and_a_new_item(api):
    """Publication is the point of no return for the version's contents.

    PRD: "Once a version is `PUBLISHED`, its items are immutable — any further
    attempt to add an item is refused with `ERR_MENU_VERSION_LOCKED`, and so is any
    attempt to freeze a version that is not currently `DRAFT`."

    Design: Corner/state_machines/state_menu_version_finalize_twice_rejected
    """
    set_clock()
    version = create_menu_version()
    add_menu_item(version["id"], burger_item_payload())
    finalize_menu_version(version["id"])
    admin = make_admin_headers()

    second_freeze = api.finalize_menu_version(version["id"], admin)
    validate_error(second_freeze, ApiErrorId.ERR_MENU_VERSION_LOCKED, 409)

    late_item = api.create_menu_item(version["id"], fries_item_payload(), admin)
    validate_error(late_item, ApiErrorId.ERR_MENU_VERSION_LOCKED, 409)

    unchanged = read_menu_version(version["id"])
    assert unchanged["state"] == "PUBLISHED"
    assert unchanged["item_count"] == 1, "the refused item was never created"
    rows, meta = validate_paginated(api.list_menu_items(version["id"], admin))
    assert meta["total_count"] == 1
    assert {row["sku"] for row in rows} == {"BURGER"}


def test_an_empty_catalogue_cannot_be_frozen_until_it_holds_an_item(api):
    """One item is a precondition of the transition, not a nicety.

    PRD: "A version with no items cannot be frozen: an attempt while `item_count` is
    zero is refused with `ERR_MENU_VERSION_EMPTY`, and at least one item is therefore
    a precondition of the transition."

    Design: Corner/state_machines/state_menu_version_finalize_empty_rejected
    """
    set_clock()
    version = create_menu_version()

    refused = api.finalize_menu_version(version["id"], make_admin_headers())

    validate_error(refused, ApiErrorId.ERR_MENU_VERSION_EMPTY, 409)
    still_draft = read_menu_version(version["id"])
    assert still_draft["state"] == "DRAFT"
    assert still_draft["published_at"] is None

    add_menu_item(version["id"], burger_item_payload())
    frozen = validate_success(api.finalize_menu_version(version["id"], make_admin_headers()))
    assert frozen["state"] == "PUBLISHED"
    assert frozen["item_count"] == 1


def test_marking_an_order_ready_twice_does_not_release_a_second_prep_slot(api):
    """The refused repeat must not drive the slot count below zero.

    PRD: "Marking an order ready is the kitchen's signal that the food is made. It
    moves `fulfillment_status` from `PREPARING` to `READY` and decrements the store's
    `reserved_prep_slots` by 1 — the slot is released because the kitchen work is
    done — while leaving `open_order_count` untouched". "It also requires a
    `fulfillment_status` of `PREPARING`, or the request is refused with
    `ERR_INVALID_ORDER_STATE`."

    Design: Corner/state_machines/state_order_second_ready_rejected
    """
    env = setup_published_store(**BURGER_ONLY)
    order = place_ready_order(env, external_ref="MP-1001", **PICKUP_BURGER)
    assert order["fulfillment_status"] == "READY"
    assert_store_counters(read_store(env["store"]["id"]), open_order_count=1, reserved_prep_slots=0)

    repeat = api.mark_order_ready(order["id"], env["store_headers"])

    validate_error(repeat, ApiErrorId.ERR_INVALID_ORDER_STATE, 409)
    assert read_order(order["id"])["fulfillment_status"] == "READY"
    assert_store_counters(read_store(env["store"]["id"]), open_order_count=1, reserved_prep_slots=0)


def test_a_saturated_tablet_queue_turns_the_next_register_failure_terminal(api):
    """The first failure fills the tablet queue; the second one cancels the order.

    PRD: "When the store's `tablet_backlog_count` is strictly less than its
    `tablet_backlog_threshold`, the order moves from `PENDING` to `TABLET_FALLBACK`
    and the store's `tablet_backlog_count` is incremented — the ticket will be worked
    from the tablet. When the store's `tablet_backlog_count` has already reached or
    passed its `tablet_backlog_threshold`, the tablet queue is saturated and the order
    moves from `PENDING` to the terminal `FAILED`: its `fulfillment_status` is set to
    `CANCELLED`, the store's `reserved_prep_slots` and `open_order_count` are each
    decremented". "Both branches still record the `REJECTED` attempt."

    Design: Corner/state_machines/state_injection_failure_terminal_cancels_order_and_releases_slot
    """
    env = setup_published_store(
        store_overrides={"pos_retry_limit": 1, "tablet_backlog_threshold": 1,
                         "prep_capacity_per_bucket": 2},
        **BURGER_ONLY,
    )
    first = place_order(env, external_ref="MP-1001", **PICKUP_BURGER)
    second = place_order(env, external_ref="MP-1002", **PICKUP_BURGER)
    assert_store_counters(read_store(env["store"]["id"]), open_order_count=2, reserved_prep_slots=2)

    fell_back = inject_order(env, first["id"], pos_result_code="TIMEOUT")
    failed = inject_order(env, second["id"], pos_result_code="TIMEOUT")

    assert fell_back["injection_status"] == "TABLET_FALLBACK"
    assert fell_back["injection_attempt_count"] == 1
    assert fell_back["fulfillment_status"] == "PREPARING"
    assert failed["injection_status"] == "FAILED"
    assert failed["fulfillment_status"] == "CANCELLED", (
        "the tablet queue was already saturated, so the register path ended the order"
    )

    store = read_store(env["store"]["id"])
    assert store["tablet_backlog_count"] == 1, "the cancelled order never joined the tablet queue"
    assert_store_counters(store, open_order_count=1, reserved_prep_slots=1)

    attempts, meta = validate_paginated(
        api.list_injection_attempts(second["id"], env["store_headers"])
    )
    assert meta["total_count"] == 1
    assert_pos_injection_attempt(attempts[0])
    assert attempts[0]["attempt_number"] == 1
    assert attempts[0]["outcome"] == "REJECTED"


def test_a_tablet_order_that_finally_reaches_the_register_drains_the_backlog(api):
    """Tablet fallback is a detour, not a dead end, and the promise does not move.

    PRD: "On `OK` the order moves from `PENDING` to `ACCEPTED`, and an order already
    in `TABLET_FALLBACK` that finally gets an `OK` also moves to `ACCEPTED`,
    additionally decrementing the store's `tablet_backlog_count` because the ticket
    has left the tablet queue." "Once pinned, `promised_ready_at` is never recomputed
    — a later throttle change, a later order, or a later clock movement does not move
    it".

    Design: Corner/state_machines/state_tablet_fallback_resolves_to_accepted_and_drains_backlog
    """
    env = setup_published_store(
        store_overrides={"pos_retry_limit": 1, "tablet_backlog_threshold": 1}, **BURGER_ONLY
    )
    order = place_order(env, external_ref="MP-1001", **PICKUP_BURGER)
    promised = order["promised_ready_at"]
    assert_instant(promised, "2026-08-03T16:12:00Z", "promised_ready_at")
    fell_back = inject_order(env, order["id"], pos_result_code="TIMEOUT")
    assert fell_back["injection_status"] == "TABLET_FALLBACK"
    assert read_store(env["store"]["id"])["tablet_backlog_count"] == 1

    accepted = inject_order(env, order["id"], pos_result_code="OK")

    assert accepted["injection_status"] == "ACCEPTED"
    assert accepted["injection_attempt_count"] == 2
    assert_instant(accepted["promised_ready_at"], "2026-08-03T16:12:00Z", "promised_ready_at")
    store = read_store(env["store"]["id"])
    assert store["tablet_backlog_count"] == 0
    assert store["reserved_prep_slots"] == 1

    attempts, meta = validate_paginated(
        api.list_injection_attempts(order["id"], env["store_headers"])
    )
    assert meta["total_count"] == 2
    by_number = {attempt["attempt_number"]: attempt["outcome"] for attempt in attempts}
    assert by_number == {1: "REJECTED", 2: "ACCEPTED"}


def test_a_declined_offer_is_terminal_but_frees_the_order_to_be_offered_again(api):
    """Accepting a declined assignment fails; dispatching the order again succeeds.

    PRD: "Declining is the mirror image and is likewise legal only from `OFFERED`."
    "The order becomes re-dispatchable, and the network's `open_assignment_count` is
    recomputed. `DECLINED` is terminal for that assignment." "Acceptance is the
    courier agent's action and is legal only from `OFFERED`; anything else is
    `ERR_INVALID_ASSIGNMENT_STATE`."

    Design: Corner/state_machines/state_assignment_declined_is_terminal_rejects_accept
    """
    env = setup_published_store(**BURGER_ONLY)
    network = create_courier_network(
        code="N_MKT", name="MarketCouriers", network_type="MARKETPLACE", priority_rank=1,
        max_concurrent_assignments=5,
    )
    order = place_injected_order(
        env, external_ref="MP-2001", fulfillment_mode="DELIVERY", lines=BURGER_LINE, tip_cents=0
    )
    first = dispatch_order(env, order["id"])
    assert first["state"] == "OFFERED"

    declined = decline_assignment(first)

    assert declined["state"] == "DECLINED"
    assert read_network(network["id"])["open_assignment_count"] == 0

    late_accept = api.accept_assignment(first["id"], make_courier_agent_headers(network["id"]))
    validate_error(late_accept, ApiErrorId.ERR_INVALID_ASSIGNMENT_STATE, 409)
    assert read_assignment(first["id"])["state"] == "DECLINED"

    second = dispatch_order(env, order["id"])
    assert_delivery_assignment(second)
    assert second["state"] == "OFFERED"
    assert second["courier_network_id"] == network["id"]
    assert second["id"] != first["id"]

    _rows, meta = validate_paginated(
        api.list_delivery_assignments(env["store_headers"], params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 2, "both the declined offer and the live one are on record"


def test_eighty_sixing_the_only_item_bubbles_the_whole_catalogue_dark(api):
    """The version's state follows its listings without anyone calling it directly.

    PRD: "If, after propagation completes, every listing referencing any item of the
    store's active version has `eighty_sixed` true, and that version's
    `published_store_count` is at least 1, the version itself moves from `PUBLISHED`
    to `EXHAUSTED`". "Symmetrically, if after propagation at least one listing of an
    `EXHAUSTED` version has `eighty_sixed` false, the version returns from
    `EXHAUSTED` to `PUBLISHED`, with no further side effects."

    Design: Corner/state_machines/state_menu_version_bubbles_to_exhausted_when_every_item_eighty_sixed
    """
    env = setup_published_store(**BURGER_ONLY)
    assert read_menu_version(env["menu_version"]["id"])["state"] == "PUBLISHED"

    darkened = record_availability_event(env, "BURGER")

    assert darkened["propagated_listing_count"] == 1
    assert darkened["skipped_listing_count"] == 0
    assert darkened["held_order_count"] == 0, "no order existed to hold"
    exhausted = read_menu_version(env["menu_version"]["id"])
    assert exhausted["state"] == "EXHAUSTED"
    assert exhausted["published_store_count"] == 1, "the store is still running this version"

    record_availability_event(env, "BURGER", event_type="RESTORE")

    assert read_menu_version(env["menu_version"]["id"])["state"] == "PUBLISHED"
    listing = listing_for(env, "BURGER")
    assert listing["eighty_sixed"] is False
    assert listing["availability_state"] == "AVAILABLE"


def test_disputing_a_reconciled_statement_unwinds_the_account_completely(api):
    """Every aggregate returns to zero and the order becomes assignable again.

    PRD: "It takes a `reason_code`, moves the statement `RECONCILED → DISPUTED`, and
    unwinds the account completely: every assigned order returns to `SETTLEABLE` with
    its `remittance_statement_id` cleared, every adjustment that had been pulled onto
    the statement is unassigned from it, `order_count` and every money aggregate —
    `gross_sales_cents`, `adjustment_total_cents`, `tier_base_cents`,
    `commission_cents`, `rebate_cents` and `net_payable_cents` — are reset to 0, and
    `tier` is reset to `TIER_1`."

    Design: Corner/state_machines/state_statement_dispute_releases_orders_and_zeroes_aggregates
    """
    env = setup_published_store(**BURGER_ONLY)
    order = place_ready_order(env, external_ref="MP-1001", **PICKUP_BURGER)
    statement = setup_reconciled_statement(env, [order])

    assert_remittance_statement(statement)
    assert statement["state"] == "RECONCILED"
    assert statement["order_count"] == 1
    assert statement["gross_sales_cents"] == 1564, "1265 of subtotal plus the 299 service fee"
    assert statement["tier_base_cents"] == 1564
    assert statement["commission_cents"] == 391
    assert statement["net_payable_cents"] == 1173

    disputed = dispute_statement(statement)

    assert disputed["state"] == "DISPUTED"
    assert disputed["order_count"] == 0
    assert disputed["gross_sales_cents"] == 0
    assert disputed["adjustment_total_cents"] == 0
    assert disputed["tier_base_cents"] == 0
    assert disputed["commission_cents"] == 0
    assert disputed["rebate_cents"] == 0
    assert disputed["net_payable_cents"] == 0
    assert disputed["tier"] == "TIER_1"

    released = read_order(order["id"])
    assert released["settlement_status"] == "SETTLEABLE"
    assert released["remittance_statement_id"] is None
    _rows, meta = validate_paginated(
        api.list_orders(
            make_analyst_headers(), params={"remittance_statement_id": statement["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert read_statement(statement["id"])["state"] == "DISPUTED"
