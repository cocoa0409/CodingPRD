"""The rejection ladder: which rung wins when one request breaks several rules,
plus the write gates and order-shape rungs in isolation."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    add_line,
    add_menu_item,
    api_client,
    create_window,
    lines_of,
    open_order,
    read_capacity,
    read_order,
    read_window,
    set_clock,
    setup_held_order,
    setup_storefront,
    validate_error,
    validate_paginated,
    validate_success,
    window_version,
)


def test_the_locked_window_gate_preempts_the_cutoff_rung(api):
    """PRD §2.6: "The offer window the call touches does not have `window_status`
    `LOCKED`; if it does, the call is rejected with `ERR_WINDOW_LOCKED` (409)."
    PRD §2.6: "For any request that violates more than one rung, **the
    lowest-numbered violated rung wins and no later rung is evaluated at all**."
    PRD §2.6: "Rung 17: the current instant is strictly before the window's
    `order_cutoff_at`; an instant exactly equal to the cutoff is already past it,
    and the rejection is `ERR_CUTOFF_PASSED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/window_locked_preempts_cutoff_passed_on_line_add
    """
    s = setup_storefront(window_overrides={"label": "To be locked"})
    control = create_window(s.baker_id, open_it=True, label="Control")
    order_locked = open_order(s.customer_id, s.window_id)
    open_order(s.customer_id, control["id"])

    set_clock("2026-05-06T12:00:00Z")
    locked = validate_success(api.lock_offer_window(s.window_id, s.bh))
    assert locked["window_status"] == "LOCKED"

    rejected = api.add_order_line(
        order_locked["id"],
        {
            "menu_item_id": s.cookie_id,
            "quantity": 13,
            "expected_offer_window_version": locked["version"],
        },
        s.ch,
    )
    error = validate_error(rejected, ApiErrorId.ERR_WINDOW_LOCKED)
    assert error["error_id"] != "ERR_CUTOFF_PASSED", (
        "the cutoff has also passed, but rung 16 is lower than rung 17"
    )
    assert error["error_id"] != "ERR_WINDOW_NOT_OPEN"
    assert read_order(order_locked["id"], s.ch)["order_status"] == "DRAFT"


def test_the_cutoff_rung_is_independently_reachable_on_an_open_window(api):
    """PRD §2.6: "Rung 17: the current instant is strictly before the window's
    `order_cutoff_at`; an instant exactly equal to the cutoff is already past it,
    and the rejection is `ERR_CUTOFF_PASSED` (409)."
    PRD §2.6: "This rung applies to four operations: line addition, line patching,
    order confirmation, and club-cycle confirmation."

    Design: Difficulty/priority_pair_validation_conflict/window_locked_preempts_cutoff_passed_on_line_add
    """
    s = setup_storefront(window_overrides={"label": "To be locked"})
    control = create_window(s.baker_id, open_it=True, label="Control")
    order_control = open_order(s.customer_id, control["id"])
    control_version = control["version"]

    set_clock("2026-05-06T12:00:00Z")
    rejected = api.add_order_line(
        order_control["id"],
        {
            "menu_item_id": s.cookie_id,
            "quantity": 13,
            "expected_offer_window_version": control_version,
        },
        s.ch,
    )
    validate_error(rejected, ApiErrorId.ERR_CUTOFF_PASSED)
    assert read_window(control["id"], s.bh)["window_status"] == "OPEN"
    assert read_order(order_control["id"], s.ch)["order_status"] == "DRAFT"
    assert lines_of(order_control["id"], s.ch) == []


def test_the_quantity_range_rung_preempts_the_units_capacity_rung(api):
    """PRD §2.6: "Rung 34: the order has at most 12 lines that are not `RELEASED`
    and not `RECALL_VOID`, and the requested `quantity` is between 1 and 120
    inclusive; a violation of either half is `ERR_MAX_LINES_EXCEEDED` (422) on line
    addition and line patching."
    PRD §2.6: "For any request that violates more than one rung, **the
    lowest-numbered violated rung wins and no later rung is evaluated at all**."

    Design: Difficulty/priority_pair_validation_conflict/max_lines_rung_preempts_units_capacity_rung
    """
    s = setup_storefront(
        window_overrides={
            "label": "Tiny window",
            "capacity_units": 10,
            "capacity_batch_slots": 12,
            "capacity_oven_hours": 18.0,
        }
    )
    order = open_order(s.customer_id, s.window_id)
    starting_version = s.window["version"]

    rejected = api.add_order_line(
        order["id"],
        {
            "menu_item_id": s.cookie_id,
            "quantity": 130,
            "expected_offer_window_version": starting_version,
        },
        s.ch,
    )
    error = validate_error(rejected, ApiErrorId.ERR_MAX_LINES_EXCEEDED)
    assert error["error_id"] != "ERR_UNITS_CAPACITY_EXCEEDED", (
        "the ten-unit window is also overrun, but rung 34 is lower than rung 53"
    )
    window = read_window(s.window_id, s.bh)
    assert window["held_units"] == 0
    assert window["version"] == starting_version
    assert read_order(order["id"], s.ch)["order_status"] == "DRAFT"


def test_the_units_capacity_rung_is_independently_reachable(api):
    """PRD §2.6: "Rung 53: the window's remaining orderable units are at least the
    unit delta the request asks for, otherwise `ERR_UNITS_CAPACITY_EXCEEDED` (422);
    this applies to line addition, line patching, and club-cycle generation."
    PRD §2.9: "Remaining orderable units are the window's `capacity_units` less
    confirmed units, less held units, less reserved units."

    Design: Difficulty/priority_pair_validation_conflict/max_lines_rung_preempts_units_capacity_rung
    """
    s = setup_storefront(
        window_overrides={
            "label": "Tiny window",
            "capacity_units": 10,
            "capacity_batch_slots": 12,
            "capacity_oven_hours": 18.0,
        }
    )
    order = open_order(s.customer_id, s.window_id)
    starting_version = s.window["version"]

    rejected = api.add_order_line(
        order["id"],
        {
            "menu_item_id": s.cookie_id,
            "quantity": 11,
            "expected_offer_window_version": starting_version,
        },
        s.ch,
    )
    validate_error(rejected, ApiErrorId.ERR_UNITS_CAPACITY_EXCEEDED)
    window = read_window(s.window_id, s.bh)
    assert window["held_units"] == 0
    assert window["version"] == starting_version
    assert read_capacity(s.window_id, s.bh)["units_remaining"] == 10


def test_a_stale_window_version_preempts_the_product_class_gate(api):
    """PRD §2.6: "Rung 20: `expected_offer_window_version` equals the offer window's
    current `version`, otherwise `ERR_STALE_OFFER_WINDOW_VERSION` (412), on line
    addition and line patching."
    PRD §2.6: "Rung 25: every referenced menu item's `product_class` is
    `SHELF_STABLE`, since a `REFRIGERATION_REQUIRED` item may not be sold direct,
    otherwise `ERR_PRODUCT_CLASS_NOT_DTC_ELIGIBLE` (422); this applies to line
    addition, subscription creation, and menu-item listing-status changes."
    PRD §2.7: "A request that is both stale and over capacity reports staleness."

    Design: Difficulty/priority_pair_validation_conflict/stale_window_version_preempts_product_class_gate
    """
    s = setup_storefront()
    add_menu_item(
        s, kind="cookie", list_it=False, key="cheese", name="Basque Cheesecake",
        product_class="REFRIGERATION_REQUIRED", pricing_basis="PER_UNIT",
        unit_price_cents=3200, dozen_price_cents=34000,
    )
    stale_version = s.window["version"]
    order = open_order(s.customer_id, s.window_id)
    add_line(order["id"], s.cookie_id, 13, s.customer_id, s.window_id)

    rejected = api.add_order_line(
        order["id"],
        {
            "menu_item_id": s.cheese_id,
            "quantity": 1,
            "expected_offer_window_version": stale_version,
        },
        s.ch,
    )
    error = validate_error(rejected, ApiErrorId.ERR_STALE_OFFER_WINDOW_VERSION)
    assert error["error_id"] != "ERR_PRODUCT_CLASS_NOT_DTC_ELIGIBLE", (
        "the refrigerated item also breaks rung 25, but rung 20 is lower"
    )
    assert window_version(s.window_id, s.ch) == stale_version + 1, (
        "the accepted cookie line bumped the window exactly once"
    )
    assert len(lines_of(order["id"], s.ch)) == 1


def test_the_product_class_gate_fires_once_the_window_version_is_fresh(api):
    """PRD §2.6: "Rung 25: every referenced menu item's `product_class` is
    `SHELF_STABLE`, since a `REFRIGERATION_REQUIRED` item may not be sold direct,
    otherwise `ERR_PRODUCT_CLASS_NOT_DTC_ELIGIBLE` (422); this applies to line
    addition, subscription creation, and menu-item listing-status changes."
    PRD §2.8: "**Only shelf-stable product may be sold direct.** A menu item's
    `product_class` is either `SHELF_STABLE` or `REFRIGERATION_REQUIRED`, and only
    the former is eligible for direct-to-consumer sale."

    Design: Difficulty/priority_pair_validation_conflict/stale_window_version_preempts_product_class_gate
    """
    s = setup_storefront()
    add_menu_item(
        s, kind="cookie", list_it=False, key="cheese", name="Basque Cheesecake",
        product_class="REFRIGERATION_REQUIRED", pricing_basis="PER_UNIT",
        unit_price_cents=3200, dozen_price_cents=34000,
    )
    order = open_order(s.customer_id, s.window_id)
    add_line(order["id"], s.cookie_id, 13, s.customer_id, s.window_id)

    rejected = api.add_order_line(
        order["id"],
        {
            "menu_item_id": s.cheese_id,
            "quantity": 1,
            "expected_offer_window_version": window_version(s.window_id, s.ch),
        },
        s.ch,
    )
    validate_error(rejected, ApiErrorId.ERR_PRODUCT_CLASS_NOT_DTC_ELIGIBLE)
    assert len(lines_of(order["id"], s.ch)) == 1


def test_a_wholesale_channel_order_can_never_be_created(api):
    """PRD §2.6: "Rung 24: the order's `channel` is `DTC`, because wholesale is not
    permitted to a cottage-food operation, otherwise `ERR_WHOLESALE_NOT_PERMITTED`
    (422); this applies to order creation and order confirmation."
    PRD §2.8: "**Wholesale is not permitted.** An order's `channel` may be recorded
    as `WHOLESALE` — the value is a member of the field's declared set — but such an
    order can never be created or confirmed; the attempt is rejected as described at
    rung 24."

    Design: Corner/validations/wholesale_channel_is_rejected_for_a_cottage_food_operation
    """
    s = setup_storefront()
    rejected = api.create_order(
        {
            "customer_id": s.customer_id,
            "offer_window_id": s.window_id,
            "handoff_mode": "PICKUP_COUNTER",
            "channel": "WHOLESALE",
        },
        s.ch,
    )
    validate_error(rejected, ApiErrorId.ERR_WHOLESALE_NOT_PERMITTED)

    accepted = validate_success(
        api.create_order(
            {
                "customer_id": s.customer_id,
                "offer_window_id": s.window_id,
                "handoff_mode": "PICKUP_COUNTER",
                "channel": "DTC",
            },
            s.ch,
        ),
        201,
    )
    assert accepted["channel"] == "DTC"
    assert accepted["order_status"] == "DRAFT"
    _, meta = validate_paginated(
        api.list_orders(s.ch, {"customer_id": s.customer_id})
    )
    assert meta["total_count"] == 1


def test_an_order_cannot_be_opened_against_a_draft_window(api):
    """PRD §2.6: "Rung 18: the window's `window_status` is `OPEN`, otherwise
    `ERR_WINDOW_NOT_OPEN` (409); this applies to six operations — order creation,
    line addition, line patching, order confirmation, club-cycle generation, and
    club-cycle confirmation."
    PRD §3.5: "A buyer opens an order against an `OPEN` window by naming the
    `customer_id` and the `offer_window_id` together with the `handoff_mode` that
    selects the fulfilment pipeline"

    Design: Corner/state_machines/order_create_on_a_draft_window_returns_window_not_open
    """
    s = setup_storefront(open_window=False, window_overrides={"label": "Still draft"})
    assert read_window(s.window_id, s.bh)["window_status"] == "DRAFT"

    rejected = api.create_order(
        {
            "customer_id": s.customer_id,
            "offer_window_id": s.window_id,
            "handoff_mode": "PICKUP_COUNTER",
        },
        s.ch,
    )
    error = validate_error(rejected, ApiErrorId.ERR_WINDOW_NOT_OPEN)
    assert error["error_id"] != "ERR_WINDOW_LOCKED"
    _, meta = validate_paginated(
        api.list_orders(s.ch, {"offer_window_id": s.window_id})
    )
    assert meta["total_count"] == 0


def test_cancelling_an_already_cancelled_order_is_refused(api):
    """PRD §2.6: "Rung 19: the target entity's current state on the relevant axis is
    a declared source state of the requested transition, otherwise
    `ERR_INVALID_STATE` (409)."
    PRD §3.5: "Every cancellation bumps the order's `version`, and `CANCELLED` is
    terminal."
    PRD §3.5: "From `PENDING_HOLD`, every `PENDING` line moves to `RELEASED` and
    `held_units` drops accordingly."

    Design: Corner/state_machines/cancel_an_already_cancelled_order_returns_invalid_state
    """
    s = setup_held_order(quantity=13)
    first = validate_success(
        api.cancel_order(s.order_id, s.ch, {"cancel_reason": "first cancel"})
    )
    assert first["order_status"] == "CANCELLED"

    rejected = api.cancel_order(s.order_id, s.ch, {"cancel_reason": "second cancel"})
    validate_error(rejected, ApiErrorId.ERR_INVALID_STATE)

    window = read_window(s.window_id, s.bh)
    assert window["held_units"] == 0
    assert window["confirmed_units"] == 0
    assert read_capacity(s.window_id, s.bh)["units_remaining"] == 240, (
        "a double release would have reported 253"
    )


def test_a_suspended_permit_blocks_the_confirm_until_reinstatement(api):
    """PRD §2.6: "The owning operator's `permit_status` is `ACTIVE`; a `PENDING`,
    `SUSPENDED`, or `CAP_REACHED` permit blocks the call with
    `ERR_PERMIT_NOT_ACTIVE` (409)."
    PRD §3.1: "`ACTIVE` to `SUSPENDED` is the compliance stop: from that instant,
    every one of those twelve writes for this operator fails at rung 15 with
    `ERR_PERMIT_NOT_ACTIVE`, while recalls, cancellations, refunds, reviews, and
    reinstatement itself remain available."
    PRD §3.1: "`SUSPENDED` back to `ACTIVE` is a plain reinstatement loop — no order
    state anywhere is rewound."

    Design: Corner/state_machines/suspended_permit_blocks_order_confirm_but_not_cancel
    """
    s = setup_held_order(quantity=13)
    suspended = validate_success(
        api.set_permit_status(s.baker_id, {"to_status": "SUSPENDED"}, ADMIN)
    )
    assert suspended["permit_status"] == "SUSPENDED"

    blocked = api.confirm_order(s.order_id, s.ch, {})
    validate_error(blocked, ApiErrorId.ERR_PERMIT_NOT_ACTIVE)

    reinstated = validate_success(
        api.set_permit_status(s.baker_id, {"to_status": "ACTIVE"}, ADMIN)
    )
    assert reinstated["permit_status"] == "ACTIVE"

    confirmed = validate_success(api.confirm_order(s.order_id, s.ch, {}))
    assert confirmed["subtotal_cents"] == 4600
    assert confirmed["order_status"] == "CONFIRMED"
