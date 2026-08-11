"""Planning the bake, the oven-hours variant, the yield fork, the under-yield
cascade, and labels as the gate on handoff."""
import pytest
from test_helpers import (
    ApiErrorId,
    CLOCK_AT_HANDOFF,
    add_line,
    api_client,
    assert_batch,
    assert_label,
    assert_money_movement,
    assert_refund_legs_sum_to_amount,
    assert_rejected,
    assert_same_instant,
    assert_yield_conservation,
    bake_batch,
    batches_of,
    confirm_yield,
    drive_to_in_production,
    instant_plus,
    issue_label,
    lines_of,
    movements_of,
    read_batch,
    read_capacity,
    read_customer,
    read_label,
    read_line,
    read_menu_item,
    read_order,
    read_recipe,
    read_window,
    recipe_version,
    set_clock,
    setup_confirmed_order,
    setup_fulfilled_order,
    setup_held_order,
    setup_ready_pickup_order,
    setup_two_item_planned_window,
    setup_under_yield_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_two_batches_of_one_slot_diverge_on_oven_hours_by_profile_alone(api):
    """PRD §2.9: "When a menu item's `oven_profile` is `STANDARD`, its oven hours are
    its `slot_count` multiplied by the fixed 1.5 hours a slot costs, rounded half up
    to 2 decimals — the item's own `oven_hours_per_batch` value is ignored entirely
    in this variant."
    PRD §2.9: "When the profile is `LONG_BAKE`, the item's own `oven_hours_per_batch`
    replaces that fixed figure, so the same slot count can consume a quite different
    share of the window's oven capacity."
    PRD §3.7: "Requesting the `PLAN` mode on a `LOCKED`, `UNPLANNED` window creates
    **one batch per distinct menu item** appearing across the `CONFIRMED` orders on
    that window."

    Design: Difficulty/dual_variant_calc/oven_hours_profile_variant_diverges_on_identical_slot_count
    """
    s = setup_two_item_planned_window(cookie_quantity=13, loaf_quantity=13)
    cookie_batch = read_batch(s.cookie_batch_id, s.bh)
    loaf_batch = read_batch(s.loaf_batch_id, s.bh)
    assert_batch(cookie_batch)
    assert_batch(loaf_batch)

    assert cookie_batch["slot_count"] == 1
    assert loaf_batch["slot_count"] == 1
    assert cookie_batch["oven_hours"] == pytest.approx(1.5)
    assert loaf_batch["oven_hours"] == pytest.approx(3.0)
    assert cookie_batch["oven_hours"] != loaf_batch["oven_hours"], (
        "identical slot counts, so only the profile can have changed the figure"
    )


def test_planned_yield_follows_each_items_own_yield_per_slot(api):
    """PRD §3.7: "its `slot_count` and `planned_yield_units` follow the per-item
    arithmetic of §2.9 (demand divided by the 24 units a slot holds and rounded up,
    then multiplied by that item's `yield_units_per_slot`)"
    PRD §3.3: "`yield_units_per_slot` defaults to 24, the same figure as a slot's
    nominal unit capacity, and states how many units one batch slot of this item
    actually produces."
    PRD §2.9: "The window's `oven_hours_used` is the sum over menu items, and
    `oven_hours_remaining` is `capacity_oven_hours` less `oven_hours_used`."

    Design: Difficulty/dual_variant_calc/oven_hours_profile_variant_diverges_on_identical_slot_count
    """
    s = setup_two_item_planned_window(cookie_quantity=13, loaf_quantity=13)
    assert read_batch(s.cookie_batch_id, s.bh)["planned_yield_units"] == 24
    assert read_batch(s.loaf_batch_id, s.bh)["planned_yield_units"] == 12

    capacity = read_capacity(s.window_id, s.bh)
    assert capacity["oven_hours_used"] == pytest.approx(4.5)
    assert capacity["oven_hours_remaining"] == pytest.approx(13.5)


def test_yield_conservation_holds_on_the_surplus_fork(api):
    """PRD §3.7: "When the actual yield is greater than or equal to that demand, the
    batch moves to `YIELD_CONFIRMED`: every `PENDING` line pointing at it moves to
    `ALLOCATED` with `allocated_units` equal to its `quantity` and `shorted_units` at
    0, and `surplus_units` is set to the actual yield less the total allocated."
    PRD §2.10: "For a batch, the summed `allocated_units` of its order lines whose
    `line_status` is `ALLOCATED`, `SHORTED`, `CREDITED`, or `FULFILLED`, plus the
    batch's `surplus_units`, equals the batch's `actual_yield_units`."
    PRD §3.7: "Either way, at the end of the same request the batch auto-advances to
    `ALLOCATED` provided the yield conservation invariant of §2.10 holds"

    Design: Difficulty/compensating_invariant/yield_conservation_holds_on_both_surplus_and_shortfall_forks
    """
    s = setup_two_item_planned_window(cookie_quantity=26, loaf_quantity=4)
    assert read_batch(s.cookie_batch_id, s.bh)["planned_yield_units"] == 48
    assert read_batch(s.loaf_batch_id, s.bh)["planned_yield_units"] == 12

    bake_batch(s, s.cookie_batch_id)
    batch = confirm_yield(s, s.cookie_batch_id, 40)
    assert batch["surplus_units"] == 14
    assert batch["batch_status"] == "ALLOCATED"

    line = read_line(s.cookie_line_id, s.ch)
    assert line["allocated_units"] == 26
    assert line["shorted_units"] == 0
    assert line["line_status"] == "ALLOCATED"
    assert_yield_conservation(read_batch(s.cookie_batch_id, s.bh), [line])


def test_yield_conservation_holds_on_the_shortfall_fork_with_its_credit(api):
    """PRD §3.7: "When the actual yield falls short of demand, the batch moves to
    `UNDER_YIELD` instead, `surplus_units` is set to 0, and a four-hop cascade runs."
    PRD §3.7: "Every `SHORTED` line then moves on to `CREDITED` in the third hop,
    carrying a proportional credit: the line's `line_total_cents` plus its
    `line_tax_cents`, multiplied by its `shorted_units` over its `quantity`,
    multiplied by a shortfall multiplier of **1.00** — the buyer is made whole, with
    no haircut and no penalty — and rounded half up to a whole cent."
    PRD §3.7: "When the order's payment is `INITIATED` or `AUTHORIZED`, or the order
    has no payment at all, no money leaves the operator: a movement is written with
    `movement_kind` `SHORTFALL_CREDIT`, `reason` `SHORTFALL`, and `ledger_scope`
    `CUSTOMER_CREDIT` against the buyer's credit balance, and the order's
    `payment_status` is left exactly as it was."

    Design: Difficulty/compensating_invariant/yield_conservation_holds_on_both_surplus_and_shortfall_forks
    """
    s = setup_two_item_planned_window(cookie_quantity=26, loaf_quantity=4)
    bake_batch(s, s.loaf_batch_id)
    batch = confirm_yield(s, s.loaf_batch_id, 3)
    assert batch["surplus_units"] == 0
    assert batch["batch_status"] == "ALLOCATED"

    line = read_line(s.loaf_line_id, s.ch)
    assert line["allocated_units"] == 3
    assert line["shorted_units"] == 1
    assert line["line_status"] == "CREDITED"
    assert_yield_conservation(read_batch(s.loaf_batch_id, s.bh), [line])

    credits = [
        movement
        for movement in movements_of(s.bh, order_id=s.order_id)
        if movement["movement_kind"] == "SHORTFALL_CREDIT"
    ]
    assert len(credits) == 1
    movement = credits[0]
    assert_money_movement(movement)
    assert movement["reason"] == "SHORTFALL"
    assert movement["ledger_scope"] == "CUSTOMER_CREDIT"
    assert movement["amount_cents"] == 900, "3600 cents times one shorted unit of four"
    assert read_customer(s.customer_id, s.bh)["credit_balance_cents"] == 900
    assert read_order(s.order_id, s.bh)["shortfall_flag"] is True


def test_the_under_yield_cascade_fills_the_club_line_before_any_walkup(api):
    """PRD §3.7: "The **first** key is club membership: a line whose owning order has
    `source` `SUBSCRIPTION_CLUB` sorts ahead of one whose order is a walk-up."
    PRD §3.7: "Allocation then walks that sorted list greedily: each line in turn is
    granted the lesser of its own `quantity` and the units still remaining from
    `actual_yield_units`; its `allocated_units` is that grant and its `shorted_units`
    is its quantity less the grant; and the remaining pool is reduced by the grant."
    PRD §3.7: "Because each earlier-priority line is filled to its **full** quantity
    before the next line receives anything, one line can be partially shorted while
    every line behind it receives nothing at all. A line granted its full quantity
    moves to `ALLOCATED`; a line granted less moves to `SHORTED` and sets its owning
    order's `shortfall_flag` to true."
    PRD §3.6: "a prepaid club of 24 units per cycle prices at 9550 cents before the
    discount and `cycle_price_cents` 8595 after it"

    Design: Difficulty/transitive_cascade/under_yield_shortfall_depth_four_cascade_from_yield_confirmation
    """
    s = setup_under_yield_scenario(cookie_units=13)
    assert s.cycle_price_cents == 8595
    batch_before = read_batch(s.cookie_batch_id, s.bh)
    assert batch_before["slot_count"] == 3
    assert batch_before["planned_yield_units"] == 72

    batch = confirm_yield(s, s.cookie_batch_id, 30)
    assert batch["batch_status"] == "ALLOCATED"
    assert batch["surplus_units"] == 0

    club_line = read_line(s.club_line_id, s.ch)
    assert club_line["allocated_units"] == 24
    assert club_line["shorted_units"] == 0
    assert club_line["line_status"] == "ALLOCATED"

    early_line = read_line(s.early_line_id, s.ch)
    assert early_line["allocated_units"] == 6
    assert early_line["shorted_units"] == 7

    late_line = read_line(s.late_line_id, s.ch)
    assert late_line["allocated_units"] == 0
    assert late_line["shorted_units"] == 13

    assert_yield_conservation(
        read_batch(s.cookie_batch_id, s.bh), [club_line, early_line, late_line]
    )


def test_the_shortfall_credit_takes_the_refund_or_the_credit_branch(api):
    """PRD §3.7: "When the order's payment is `CAPTURED`, money leaves the operator:
    a movement is written with `movement_kind` `REFUND`, `reason` `SHORTFALL`, and
    `ledger_scope` `SETTLEMENT`, its four legs filled by the waterfall of §3.9, and
    the order's `payment_status` moves from `CAPTURED` to `PARTIALLY_REFUNDED`."
    PRD §3.7: "When the order's payment is `INITIATED` or `AUTHORIZED`, or the order
    has no payment at all, no money leaves the operator: a movement is written with
    `movement_kind` `SHORTFALL_CREDIT`, `reason` `SHORTFALL`, and `ledger_scope`
    `CUSTOMER_CREDIT` against the buyer's credit balance, and the order's
    `payment_status` is left exactly as it was."
    PRD §3.7: "Every `SHORTED` line then moves on to `CREDITED` in the third hop,
    carrying a proportional credit: the line's `line_total_cents` plus its
    `line_tax_cents`, multiplied by its `shorted_units` over its `quantity`,
    multiplied by a shortfall multiplier of **1.00** — the buyer is made whole, with
    no haircut and no penalty — and rounded half up to a whole cent."

    Design: Difficulty/transitive_cascade/under_yield_shortfall_depth_four_cascade_from_yield_confirmation
    """
    s = setup_under_yield_scenario(cookie_units=13)
    confirm_yield(s, s.cookie_batch_id, 30)

    assert read_line(s.early_line_id, s.ch)["line_status"] == "CREDITED"
    assert read_line(s.late_line_id, s.ch)["line_status"] == "CREDITED"

    early_movements = [
        movement
        for movement in movements_of(s.bh, order_id=s.early_order_id)
        if movement["reason"] == "SHORTFALL"
    ]
    assert len(early_movements) == 1
    early = early_movements[0]
    assert early["movement_kind"] == "REFUND"
    assert early["ledger_scope"] == "SETTLEMENT"
    assert early["amount_cents"] == 2477, "4600 cents times seven shorted units of 13"
    assert early["leg_tip_cents"] == 0
    assert early["leg_delivery_fee_cents"] == 0
    assert early["leg_subtotal_cents"] == 2477
    assert_refund_legs_sum_to_amount(early)

    late_movements = [
        movement
        for movement in movements_of(s.bh, order_id=s.late_order_id)
        if movement["reason"] == "SHORTFALL"
    ]
    assert len(late_movements) == 1
    late = late_movements[0]
    assert late["movement_kind"] == "SHORTFALL_CREDIT"
    assert late["ledger_scope"] == "CUSTOMER_CREDIT"
    assert late["amount_cents"] == 4600

    assert read_order(s.early_order_id, s.bh)["payment_status"] == "PARTIALLY_REFUNDED"
    assert read_order(s.early_order_id, s.bh)["shortfall_flag"] is True
    assert read_order(s.late_order_id, s.bh)["payment_status"] == "UNPAID"
    assert read_order(s.late_order_id, s.bh)["shortfall_flag"] is True
    assert read_customer(s.customer_id, s.bh)["credit_balance_cents"] == 4600


def test_confirming_yield_on_a_mixed_batch_is_refused_by_its_own_rung(api):
    """PRD §2.6: "Rung 36: the batch's `batch_status` is `BAKED`, otherwise
    `ERR_BATCH_NOT_BAKED` (409) on yield confirmation."
    PRD §3.7: "The operator supplies `actual_yield_units` for a batch that must be in
    `BAKED` — any other status is rung 36's `ERR_BATCH_NOT_BAKED`, and this rung, not
    the generic source-state rung, owns the check."

    Design: Corner/state_machines/confirm_yield_on_a_mixed_batch_returns_batch_not_baked
    """
    s = setup_confirmed_order(quantity=13)
    drive_to_in_production(s)
    validate_success(api.advance_batch(s.batch_id, {"to_status": "MIXED"}, s.bh))

    rejected = api.confirm_yield(s.batch_id, {"actual_yield_units": 24}, s.bh)
    error = validate_error(rejected, ApiErrorId.ERR_BATCH_NOT_BAKED)
    assert error["error_id"] != "ERR_INVALID_STATE"

    batch = read_batch(s.batch_id, s.bh)
    assert batch["batch_status"] == "MIXED"
    assert batch["actual_yield_units"] is None
    line = read_line(s.line_id, s.ch)
    assert line["line_status"] == "PENDING"
    assert line["allocated_units"] == 0


def test_handoff_cannot_open_until_every_batch_has_been_allocated(api):
    """PRD §3.4: "Handoff opens when an `IN_PRODUCTION` window is advanced to
    `HANDOFF_OPEN`, which requires the current instant to have reached `handoff_date`
    and **every** batch on the window to have reached `ALLOCATED`, `CLOSED`, or
    `SCRAPPED_RECALL`."
    PRD §2.6: "All of these are genuine, enforced preconditions: a request that fails
    one is rejected and nothing is mutated."

    The specification does not settle which identifier such a rejection carries, so
    only the rejection and the absence of any mutation are asserted here.

    Design: Corner/state_machines/handoff_open_advance_requires_every_batch_allocated
    """
    s = setup_confirmed_order(quantity=13)
    drive_to_in_production(s)
    bake_batch(s, s.batch_id)
    assert read_batch(s.batch_id, s.bh)["batch_status"] == "BAKED"

    set_clock(CLOCK_AT_HANDOFF)
    rejected = api.advance_offer_window(
        s.window_id, {"to_status": "HANDOFF_OPEN"}, s.bh
    )
    assert_rejected(rejected, "opening handoff while a batch is still BAKED")

    assert read_window(s.window_id, s.bh)["window_status"] == "IN_PRODUCTION"
    order = read_order(s.order_id, s.bh)
    assert order["order_status"] == "IN_PRODUCTION"
    assert order["pickup_forfeit_at"] is None


def test_republishing_a_recipe_supersedes_its_issued_labels(api):
    """PRD §3.2: "**republishing from `REVISING` back to `PUBLISHED` triggers the
    three-hop label supersession cascade**: hop one, every label whose `recipe_id` is
    this recipe and whose `label_status` is `ISSUED`, and whose pinned recipe version
    is now behind the freshly incremented `published_version`, moves from `ISSUED` to
    `SUPERSEDED`; hop two, each superseded label's order line thereby loses the
    handoff write gate, so rung 35 now blocks a handed-off outcome for the owning
    order with `ERR_LABEL_SUPERSEDED` until a fresh label is issued; hop three,
    `allergen_summary` is recomputed on every menu item backed by this recipe."
    PRD §3.7: "The label is created in `label_status` `ISSUED` with
    `recipe_version_pinned` taken from the recipe's current `published_version`"

    Design: Difficulty/transitive_cascade/recipe_republish_supersedes_labels_and_blocks_handoff_depth_three
    """
    s = setup_ready_pickup_order()
    label = read_label(s.label_id, s.bh)
    assert_label(label)
    assert label["label_status"] == "ISSUED"
    assert label["recipe_version_pinned"] == 1
    assert read_recipe(s.recipe_id, s.bh)["published_version"] == 1

    validate_success(
        api.set_recipe_lifecycle(s.recipe_id, {"to_status": "REVISING"}, s.bh)
    )
    validate_success(
        api.add_recipe_component(
            s.recipe_id,
            {
                "component_name": "toasted pecan",
                "quantity_grams": 60,
                "declared_allergens": ["tree_nut"],
            },
            s.bh,
        ),
        201,
    )
    republished = validate_success(api.publish_recipe(s.recipe_id, s.bh))
    assert republished["published_version"] == 2

    assert read_label(s.label_id, s.bh)["label_status"] == "SUPERSEDED"
    assert read_menu_item(s.cookie_id, s.bh)["allergen_summary"] == [
        "milk", "tree_nut", "wheat",
    ]


def test_a_superseded_label_blocks_the_handed_off_outcome(api):
    """PRD §2.6: "Rung 35: on a handed-off outcome, every order line that is not
    `RELEASED` and not `RECALL_VOID` has a label whose `label_status` is `ISSUED`; a
    line whose label is `SUPERSEDED`, `VOID`, `CONSUMED`, or altogether missing fails
    with `ERR_LABEL_SUPERSEDED` (409)."
    PRD §3.8: "requires **every** order line that is neither `RELEASED` nor
    `RECALL_VOID` to have a label whose `label_status` is `ISSUED`; a superseded,
    voided, already-consumed, or missing label fails at rung 35 with
    `ERR_LABEL_SUPERSEDED`."

    Design: Difficulty/transitive_cascade/recipe_republish_supersedes_labels_and_blocks_handoff_depth_three
    """
    s = setup_ready_pickup_order()
    validate_success(
        api.set_recipe_lifecycle(s.recipe_id, {"to_status": "REVISING"}, s.bh)
    )
    validate_success(
        api.add_recipe_component(
            s.recipe_id,
            {
                "component_name": "toasted pecan",
                "quantity_grams": 60,
                "declared_allergens": ["tree_nut"],
            },
            s.bh,
        ),
        201,
    )
    validate_success(api.publish_recipe(s.recipe_id, s.bh))

    rejected = api.record_handoff_outcome(
        s.order_id, {"outcome": "HANDED_OFF"}, s.bh
    )
    validate_error(rejected, ApiErrorId.ERR_LABEL_SUPERSEDED)

    order = read_order(s.order_id, s.bh)
    assert order["order_status"] == "READY"
    assert order["handoff_status"] == "PICKUP_READY"


def test_a_stale_recipe_version_blocks_label_issuance(api):
    """PRD §2.7: "`POST /bakery/labels` requires `expected_recipe_version`, carrying
    the client's last observed `version` of the `Recipe` the label derives from. A
    mismatch is rejected with `ERR_STALE_RECIPE_VERSION` (HTTP 412)."
    PRD §3.2: "Attaching a component recomputes the owning recipe's `tree_depth` and
    `allergen_union` and bumps its `version`."
    PRD §3.7: "The label is created in `label_status` `ISSUED` with
    `recipe_version_pinned` taken from the recipe's current `published_version`"

    Design: Corner/cross_cutting_layers/stale_recipe_version_blocks_label_issuance
    """
    s = setup_held_order(quantity=13)
    stale_version = recipe_version(s.recipe_id, s.bh)
    validate_success(
        api.add_recipe_component(
            s.recipe_id, {"component_name": "vanilla paste", "quantity_grams": 8}, s.bh
        ),
        201,
    )

    rejected = api.create_label(
        {
            "order_line_id": s.line_id,
            "recipe_id": s.recipe_id,
            "net_weight_grams": 320.0,
            "expected_recipe_version": stale_version,
        },
        s.bh,
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_RECIPE_VERSION)

    fresh_version = recipe_version(s.recipe_id, s.bh)
    assert fresh_version == stale_version + 1
    label = validate_success(
        api.create_label(
            {
                "order_line_id": s.line_id,
                "recipe_id": s.recipe_id,
                "net_weight_grams": 320.0,
                "expected_recipe_version": fresh_version,
            },
            s.bh,
        ),
        201,
    )
    assert label["label_status"] == "ISSUED"
    assert label["recipe_version_pinned"] == 1, (
        "recipe_version_pinned tracks published_version, a different counter"
    )
    _, meta = validate_paginated(api.list_labels(s.bh, {"order_line_id": s.line_id}))
    assert meta["total_count"] == 1


def test_a_fulfilled_order_is_terminal_on_the_handoff_axis(api):
    """PRD §3.8: "When it succeeds, the order's `handoff_status` becomes `HANDED_OFF`
    and its `order_status` moves from `READY` to `FULFILLED`; `fulfilled_at` is set to
    the current instant and `review_window_closes_at` to that instant plus **21
    days**; every line in `ALLOCATED` or `CREDITED` moves to `FULFILLED` and the label
    on each of those lines moves from `ISSUED` to `CONSUMED`; a payment sitting in
    `CAPTURED` moves to `SETTLED` and the operator's `payout_net_cents` is recomputed."
    PRD §2.6: "Rung 19: the target entity's current state on the relevant axis is a
    declared source state of the requested transition, otherwise `ERR_INVALID_STATE`
    (409)."

    Design: Corner/state_machines/fulfilled_order_is_terminal_and_rejects_a_second_handoff
    """
    s = setup_fulfilled_order()
    order = read_order(s.order_id, s.bh)
    assert order["order_status"] == "FULFILLED"
    assert order["handoff_status"] == "HANDED_OFF"
    assert_same_instant(order["fulfilled_at"], CLOCK_AT_HANDOFF, "fulfilled_at")
    assert_same_instant(
        order["review_window_closes_at"],
        instant_plus(CLOCK_AT_HANDOFF, days=21),
        "review_window_closes_at",
    )
    assert read_label(s.label_id, s.bh)["label_status"] == "CONSUMED"
    assert read_line(s.line_id, s.ch)["line_status"] == "FULFILLED"

    rejected = api.record_handoff_outcome(
        s.order_id, {"outcome": "HANDED_OFF"}, s.bh
    )
    validate_error(rejected, ApiErrorId.ERR_INVALID_STATE)
    assert read_order(s.order_id, s.bh)["order_status"] == "FULFILLED"
