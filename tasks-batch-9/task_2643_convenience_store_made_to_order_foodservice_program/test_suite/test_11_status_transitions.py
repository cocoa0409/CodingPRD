"""Every declared transition, its guards and its full side-effect set.

The batch machine is the busy one here: it claims a store-level slot on the
bake, starts a hold clock on the pull, self-loops on a partial write-off and
locks down once discarded. Alongside it sit the plan machine, the two-axis
order machine and the safety machine, each checked at one forward edge and one
refused edge.
"""

import test_helpers as H
from test_helpers import factories as F
from test_helpers import fixtures as X

CLOCK_EARLY = "2026-08-01T06:00:00Z"
CLOCK_LUNCH = "2026-08-01T11:00:00Z"
BAKE_START = "2026-08-01T06:00:00Z"
HOLD_EXPIRES = "2026-08-01T10:00:00Z"


def _store_with_a_planned_pretzel_pan(api, planned_qty=40, **store_overrides):
    """Clock at 06:00, a bakery case with three slots, one PLANNED pan."""
    X.set_clock(api, CLOCK_EARLY)
    store = X.create_store(api, **store_overrides)
    unit = X.create_bakery_case(api, store["id"], slot_count=3)
    pretzel = X.create_pretzel(api)
    batch = X.create_planned_batch(
        api, store["id"], pretzel["id"], unit["id"],
        slot_index=1, planned_qty=planned_qty, bake_start_at=BAKE_START,
    )
    return store, unit, pretzel, batch


def test_the_bake_transition_writes_the_ledger_and_claims_a_store_slot(api):
    """One call moves the status, seeds two counters and books a slot.

    "A `KitchenAssociate` ovens a batch in, driving it `PLANNED → BAKING`." The
    write is threefold: "On success the batch's `baked_qty` and `remaining_qty`
    are both set to the `planned_qty`, the store's `hot_case_slots_used`
    increases by one and the store's `version` increments by one, and the
    batch's own `version` increments by one." The hold clock is not started
    yet, because "The pull sets `hold_started_at` to the current logical-clock
    instant and `hold_expires_at` to that instant advanced by the item's
    `hold_minutes`".

    Design: Corner/state_machines/bake_moves_a_planned_batch_to_baking_and_claims_a_hot_case_slot
    """
    store, unit, pretzel, batch = _store_with_a_planned_pretzel_pan(api)
    assert batch["status"] == "PLANNED"
    assert batch["baked_qty"] == 0

    response = api.bake_production_batch(batch["id"], {}, H.KITCHEN_ASSOCIATE_HEADERS)

    baking = H.get_success_data(response, 200)
    assert baking["status"] == "BAKING"
    assert baking["baked_qty"] == 40
    assert baking["remaining_qty"] == 40
    assert baking["reserved_qty"] == 0
    assert baking["hold_started_at"] is None
    assert baking["hold_expires_at"] is None
    assert X.read_store(api, store["id"])["hot_case_slots_used"] == 1


def test_the_slot_ceiling_is_checked_at_the_store_not_at_the_cabinet(api):
    """A second bake is refused although the cabinet has two free slots.

    "The `hot_case_slot_capacity` is the ceiling on how many production batches
    the site may simultaneously hold in either the baking or the holding phase,
    and `hot_case_slots_used` is the running count of exactly those batches."
    The gate sits on the bake, not on the plan: "the store's
    `hot_case_slots_used` must be strictly below its `hot_case_slot_capacity`,
    otherwise `ERR_HOT_CASE_CAPACITY_EXCEEDED` (HTTP 409)". The refused pan
    keeps its planning posture, where "A newly planned batch opens in `PLANNED`
    with every quantity counter at 0".

    Design: Corner/state_machines/bake_beyond_the_hot_case_slot_capacity_returns_capacity_exceeded
    """
    store, unit, pretzel, batch_a = _store_with_a_planned_pretzel_pan(
        api, hot_case_slot_capacity=1
    )
    batch_b = X.create_planned_batch(
        api, store["id"], pretzel["id"], unit["id"],
        slot_index=2, planned_qty=20, bake_start_at=BAKE_START,
    )
    assert batch_b["status"] == "PLANNED"
    X.bake_batch(api, batch_a["id"])

    response = api.bake_production_batch(batch_b["id"], {}, H.KITCHEN_ASSOCIATE_HEADERS)

    H.validate_error(response, H.ApiErrorId.ERR_HOT_CASE_CAPACITY_EXCEEDED.value, 409)
    refused = X.read_batch(api, batch_b["id"])
    assert refused["status"] == "PLANNED"
    assert refused["baked_qty"] == 0
    assert X.read_batch(api, batch_a["id"])["status"] == "BAKING"
    assert X.read_store(api, store["id"])["hot_case_slots_used"] == 1


def test_a_daypart_flip_sweeps_stock_the_new_menu_no_longer_sells(api):
    """The transition writes off the pan and books both valuations.

    The flip itself is bookkeeping - "the store's `current_daypart` becomes the
    requested `to_daypart`, the `daypart_epoch` increases by one and the store's
    `version` increments" - and then "for every batch of that store which is
    currently in `HOLDING` and has a `reserved_qty` of zero, writes it off
    entirely when either of two conditions holds: its `hold_expires_at` is at or
    before the logical clock, or the menu item's `valid_dayparts` does not
    include the newly current daypart". The evidence row is stamped by the
    system: it "appends a waste record whose `reason` is `DAYPART_TRANSITION`,
    whose `logged_by_user_id` is the literal string `system`, and whose
    `daypart_epoch` is the **new** epoch value rather than the one in effect
    before the flip". Both valuations are carried, since "The **food-cost
    valuation** of a write-off is the quantity multiplied by the item's
    `unit_food_cost_cents`; the **retail valuation** of the same write-off is
    the quantity multiplied by the item's `base_price_cents`."

    Design: Corner/state_machines/daypart_transition_sweep_discards_a_batch_the_new_menu_excludes
    """
    X.set_clock(api, CLOCK_EARLY)
    store = X.create_store(api)
    unit = X.create_bakery_case(api, store["id"], slot_count=3)
    pretzel = X.create_pretzel(api, valid_dayparts=["BREAKFAST"])
    batch = X.create_holding_batch(
        api, store["id"], pretzel["id"], unit["id"],
        slot_index=1, planned_qty=40, bake_start_at=BAKE_START,
    )
    assert batch["hold_expires_at"] == HOLD_EXPIRES
    X.set_clock(api, CLOCK_LUNCH)

    response = api.create_daypart_transition(
        store["id"], F.daypart_transition_payload("LUNCH"), H.STORE_MANAGER_HEADERS
    )

    after_store = H.get_success_data(response, 200)
    assert after_store["current_daypart"] == "LUNCH"
    assert after_store["daypart_epoch"] == 1
    assert after_store["waste_cost_cents_mtd"] == 1600
    assert after_store["hot_case_slots_used"] == 0

    swept = X.read_batch(api, batch["id"])
    assert swept["status"] == "DISCARDED"
    assert swept["remaining_qty"] == 0
    assert swept["discarded_qty"] == 40

    rows, meta = H.validate_paginated(
        api.list_batch_waste_logs(batch["id"], H.STORE_MANAGER_HEADERS)
    )
    assert meta["total_count"] == 1
    H.assert_waste_log(
        rows[0],
        {
            "reason": "DAYPART_TRANSITION",
            "qty": 40,
            "food_cost_cents": 1600,
            "retail_value_cents": 7960,
            "logged_by_user_id": "system",
            "daypart_epoch": 1,
        },
    )


def test_pulling_a_pan_that_never_went_in_the_oven_is_refused(api):
    """Skipping the bake is not an implicit bake-then-pull.

    The pull is defined from one state only: "The batch must be in `BAKING`,
    otherwise `ERR_BATCH_STATE_INVALID`, and the unit must be `OPERATIONAL`".
    The refusal leaves the pan exactly as planned - "A newly planned batch opens
    in `PLANNED` with every quantity counter at 0: `baked_qty`, `remaining_qty`,
    `reserved_qty`, `sold_qty` and `discarded_qty` are all zero, and
    `hold_started_at` and `hold_expires_at` are both null" - and no store slot
    is booked, because only the bake "increases by one" the slot count.

    Design: Corner/state_machines/pull_a_planned_batch_returns_batch_state_invalid
    """
    store, unit, pretzel, batch = _store_with_a_planned_pretzel_pan(api)

    response = api.pull_production_batch(batch["id"], {}, H.KITCHEN_ASSOCIATE_HEADERS)

    H.validate_error(response, H.ApiErrorId.ERR_BATCH_STATE_INVALID.value, 409)
    unchanged = X.read_batch(api, batch["id"])
    assert unchanged["status"] == "PLANNED"
    assert unchanged["hold_started_at"] is None
    assert unchanged["hold_expires_at"] is None
    assert unchanged["baked_qty"] == 0
    assert X.read_store(api, store["id"])["hot_case_slots_used"] == 0


def test_five_fresh_rows_open_in_their_declared_initial_states(api):
    """Unit, batch, plan and both order axes all start where declared.

    "A new unit opens in the `OPERATIONAL` posture with a
    `consecutive_out_of_range_count` of 0"; "A newly planned batch opens in
    `PLANNED` with every quantity counter at 0"; "The plan's own `store_id`
    records the site it staffs, and a new plan opens in `DRAFT`." The order
    carries two axes at once: "A new order opens with a `production_status` of
    `DRAFT` on the kitchen axis and a `settlement_status` of `UNPAID` on the
    money axis. Its money counters `subtotal_gross_cents`,
    `promo_discount_cents`, `service_fee_cents` and `total_cents` all start at 0,
    as do `points_provisional` and `rework_count`."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    X.set_clock(api, CLOCK_EARLY)
    store = X.create_store(api)
    pretzel = X.create_pretzel(api)

    unit = H.get_success_data(
        api.create_holding_unit(
            store["id"], F.holding_unit_payload(slot_count=3), H.STORE_MANAGER_HEADERS
        ),
        201,
    )
    batch = H.get_success_data(
        api.create_production_batch(
            F.production_batch_payload(
                store["id"], pretzel["id"], unit["id"],
                slot_index=1, planned_qty=40, bake_start_at=BAKE_START,
            ),
            H.KITCHEN_ASSOCIATE_HEADERS,
        ),
        201,
    )
    plan = H.get_success_data(
        api.create_staffing_plan(
            store["id"],
            F.staffing_plan_payload(
                X.read_store(api, store["id"])["version"], daypart="BREAKFAST"
            ),
            H.STORE_MANAGER_HEADERS,
        ),
        201,
    )
    order = H.get_success_data(
        api.create_order(F.order_payload(store["id"]), H.STORE_TERMINAL_HEADERS), 201
    )

    assert unit["status"] == "OPERATIONAL"
    assert batch["status"] == "PLANNED"
    assert batch["remaining_qty"] == 0
    assert plan["status"] == "DRAFT"
    assert plan["version"] == 1
    assert order["production_status"] == "DRAFT"
    assert order["settlement_status"] == "UNPAID"
    assert order["daypart_at_placement"] is None
    assert order["total_cents"] == 0
    assert order["rework_count"] == 0


def test_a_discarded_pan_bounces_every_further_batch_verb(api):
    """Discard, top-off and pull all report the same state error.

    A write-off that empties the pan is an exit: "if after the write-off both
    `remaining_qty` and `reserved_qty` are zero, the batch goes `HOLDING →
    DISCARDED` and the store's `hot_case_slots_used` decreases by one". From
    there each verb has the same precondition: on a write-off "the batch must be
    in `HOLDING`, otherwise `ERR_BATCH_STATE_INVALID` — this covers a batch that
    is still planned or baking as well as one already `DISCARDED` or
    `SOLD_OUT`"; on a top-off "The batch must be in `HOLDING`, otherwise
    `ERR_BATCH_STATE_INVALID`"; and on a pull "The batch must be in `BAKING`,
    otherwise `ERR_BATCH_STATE_INVALID`". None of the three may append evidence,
    because "Validation is a fixed pipeline and the **first** failure wins".

    Design: Corner/state_machines/a_discarded_batch_rejects_every_further_transition
    """
    store, unit, pretzel, planned = _store_with_a_planned_pretzel_pan(api)
    X.bake_batch(api, planned["id"])
    holding = X.pull_batch(api, planned["id"])
    assert holding["version"] == 3

    discarded = H.get_success_data(
        api.discard_production_batch(
            planned["id"],
            F.discard_payload(40, "QUALITY_REJECT", holding["version"]),
            H.SHIFT_LEAD_HEADERS,
        )
    )
    assert discarded["status"] == "DISCARDED"

    second_discard = api.discard_production_batch(
        planned["id"],
        F.discard_payload(1, "QUALITY_REJECT", discarded["version"]),
        H.SHIFT_LEAD_HEADERS,
    )
    top_off = api.bake_production_batch(
        planned["id"], F.bake_payload(12), H.KITCHEN_ASSOCIATE_HEADERS
    )
    pull_again = api.pull_production_batch(planned["id"], {}, H.KITCHEN_ASSOCIATE_HEADERS)

    for refused in (second_discard, top_off, pull_again):
        H.validate_error(refused, H.ApiErrorId.ERR_BATCH_STATE_INVALID.value, 409)

    frozen = X.read_batch(api, planned["id"])
    assert frozen["status"] == "DISCARDED"
    assert frozen["baked_qty"] == 40
    assert frozen["remaining_qty"] == 0
    assert frozen["discarded_qty"] == 40

    rows, meta = H.validate_paginated(
        api.list_batch_waste_logs(planned["id"], H.STORE_MANAGER_HEADERS)
    )
    assert meta["total_count"] == 1
    assert rows[0]["reason"] == "QUALITY_REJECT"
    assert rows[0]["logged_by_user_id"] == H.SHIFT_LEAD_1_USER_ID

    after_store = X.read_store(api, store["id"])
    assert after_store["waste_cost_cents_mtd"] == 1600
    assert after_store["hot_case_slots_used"] == 0


def test_publishing_a_plan_twice_is_refused_and_does_not_bump_the_version(api):
    """Publication is a one-way edge, not an idempotent write.

    "A `StoreManager` publishes a plan, moving it `DRAFT → PUBLISHED`, after
    which orders may be placed at that store in that daypart on that service
    date. Publishing a plan that is not in `DRAFT` is rejected with
    `ERR_PLAN_STATE_INVALID` (HTTP 409)." The first publish is the only mutation
    the row sees, since "Both transitions increment the plan's `version` by
    one", so a refused repeat must leave the version where the accepted call
    left it.

    Design: Corner/state_machines/publishing_an_already_published_plan_returns_plan_state_invalid
    """
    X.set_clock(api, CLOCK_EARLY)
    store = X.create_store(api)
    plan = X.create_staffing_plan(api, store["id"], daypart="BREAKFAST")
    published = X.publish_staffing_plan(api, plan["id"])
    assert published["status"] == "PUBLISHED"
    assert published["version"] == 2

    response = api.publish_staffing_plan(plan["id"], {}, H.STORE_MANAGER_HEADERS)

    H.validate_error(response, H.ApiErrorId.ERR_PLAN_STATE_INVALID.value, 409)
    rows, _ = H.validate_paginated(
        api.list_staffing_plans(store["id"], H.STORE_MANAGER_HEADERS)
    )
    still = [row for row in rows if row["id"] == plan["id"]][0]
    assert still["status"] == "PUBLISHED"
    assert still["version"] == 2


def test_the_order_assembles_only_on_the_last_station_ticket(api):
    """Finishing the first of two tickets must not assemble the order.

    The bubble-up is conditional on the whole board being clear: "When after
    this completion no ticket of the order remains in `QUEUED` or
    `IN_PROGRESS`, the order advances `IN_PRODUCTION → ASSEMBLED` and its
    `version` increments". The first claim is what moved the order off
    placement, because "where the order was still `PLACED`, it also advances the
    order `PLACED → IN_PRODUCTION`". Assembly then runs straight on, since "An
    order entering `ASSEMBLED` advances immediately to `READY` when either the
    `channel` is `TOUCHSCREEN`, or the current logical clock has reached the
    order's `pickup_window_start`."

    Design: Corner/state_machines/order_assembles_only_when_the_last_station_ticket_is_done
    """
    store, hoagie, coffee, order = X.setup_authorized_order_with_tickets(api, CLOCK_LUNCH)
    sandwich = X.find_ticket(api, order["id"], "SANDWICH")
    beverage = X.find_ticket(api, order["id"], "BEVERAGE")

    X.start_ticket(api, sandwich["id"], H.KITCHEN_ASSOCIATE_HEADERS)
    X.complete_ticket(api, sandwich["id"], H.KITCHEN_ASSOCIATE_HEADERS)
    mid = X.read_order(api, order["id"])
    assert mid["production_status"] == "IN_PRODUCTION"

    X.start_ticket(api, beverage["id"], H.KITCHEN_ASSOCIATE_2_HEADERS)
    beverage_done = X.complete_ticket(api, beverage["id"], H.KITCHEN_ASSOCIATE_2_HEADERS)

    assert beverage_done["status"] == "DONE"
    assert X.read_order(api, sandwich["order_id"])["production_status"] == "READY"
    final = X.read_order(api, order["id"])
    assert final["production_status"] == "READY"
    assert final["settlement_status"] == "AUTHORIZED"
    assert final["subtotal_gross_cents"] == 1148
    tickets = X.list_order_tickets(api, order["id"])
    assert len(tickets) == 2
    assert {ticket["status"] for ticket in tickets} == {"DONE"}


def test_verifying_a_corrective_action_puts_the_case_and_the_oven_back_to_work(api):
    """One write on the action row unblocks a bake it had refused.

    "While a unit sits in `IMPAIRED` or `LOCKED_OUT`, planning, baking and
    pulling batches in it are all blocked with
    `ERR_HOLDING_UNIT_NOT_OPERATIONAL` until a corrective action has been
    verified." The action opens neutral - "The action is created in `OPEN` with
    `opened_by_user_id` set to the acting `X-User-ID`, and with
    `verified_by_user_id` and `verified_at` both null" - and a shift lead may
    close it, since "A `ShiftLead` may verify an action for an impaired unit".
    "A successful verification moves the action `OPEN → VERIFIED`, records
    `verified_by_user_id` as the acting `X-User-ID` and `verified_at` as the
    current logical-clock instant, returns the unit to service by driving it
    `IMPAIRED → OPERATIONAL` or `LOCKED_OUT → OPERATIONAL`, resets the unit's
    `consecutive_out_of_range_count` to zero".

    Design: Corner/state_machines/verifying_a_corrective_action_restores_the_unit_and_unblocks_bake
    """
    store, unit, pretzel, batch = _store_with_a_planned_pretzel_pan(api)
    reading = X.log_temperature(api, unit["id"], 120, H.KITCHEN_ASSOCIATE_HEADERS)
    assert reading["in_range"] is False

    refused = api.bake_production_batch(batch["id"], {}, H.KITCHEN_ASSOCIATE_HEADERS)
    H.validate_error(refused, H.ApiErrorId.ERR_HOLDING_UNIT_NOT_OPERATIONAL.value, 409)

    action = X.open_corrective_action(
        api, reading["id"], H.SHIFT_LEAD_HEADERS, action_taken="REPLACED_CASE_THERMOSTAT"
    )
    assert action["status"] == "OPEN"

    verified = X.verify_corrective_action(api, action["id"], H.SHIFT_LEAD_HEADERS)
    assert verified["status"] == "VERIFIED"
    assert verified["verified_by_user_id"] == H.SHIFT_LEAD_1_USER_ID
    assert verified["verified_at"].startswith("2026-08-01T06:00:00")

    restored = X.read_holding_unit(api, unit["id"])
    assert restored["status"] == "OPERATIONAL"
    assert restored["consecutive_out_of_range_count"] == 0

    baked = X.bake_batch(api, batch["id"])
    assert baked["status"] == "BAKING"
    after_store = X.read_store(api, store["id"])
    assert after_store["hot_case_slots_used"] == 1
    assert after_store["waste_cost_cents_mtd"] == 0


def test_a_partial_write_off_is_a_self_loop_that_keeps_the_slot(api):
    """Ten of forty leaves the pan holding, and only the food cost lands.

    "A successful write-off subtracts the `qty` from `remaining_qty` and adds it
    to `discarded_qty`, then appends a waste record carrying the
    `production_batch_id` of the batch, the `qty`, the `reason`, both
    valuations, a `logged_by_user_id` set to the acting `X-User-ID`, and a
    `daypart_epoch` copied from the store's `daypart_epoch` at the moment the
    write-off was booked." The pan survives because "the batch stays in
    `HOLDING` and the slot count is untouched", and the two valuations go to two
    different places: "Only the food-cost basis accumulates onto the store's
    `waste_cost_cents_mtd`; the retail basis is aggregated on demand for the
    inspection summary", where "The `retail_waste_exposure_cents` figure sums the
    `retail_value_cents` of every waste record belonging to the store's batches."

    Design: Corner/state_machines/partial_discard_syncs_the_store_waste_ledger_and_keeps_the_slot
    """
    store, unit, pretzel, planned = _store_with_a_planned_pretzel_pan(api)
    X.bake_batch(api, planned["id"])
    holding = X.pull_batch(api, planned["id"])
    assert holding["version"] == 3

    response = api.discard_production_batch(
        planned["id"],
        F.discard_payload(10, "HOLD_EXPIRED", holding["version"]),
        H.KITCHEN_ASSOCIATE_HEADERS,
    )

    after = H.get_success_data(response, 200)
    assert after["status"] == "HOLDING"
    assert after["remaining_qty"] == 30
    assert after["discarded_qty"] == 10
    assert after["baked_qty"] == 40
    assert after["reserved_qty"] == 0

    rows, meta = H.validate_paginated(
        api.list_batch_waste_logs(planned["id"], H.STORE_MANAGER_HEADERS)
    )
    assert meta["total_count"] == 1
    H.assert_waste_log(
        rows[0],
        {
            "qty": 10,
            "reason": "HOLD_EXPIRED",
            "food_cost_cents": 400,
            "retail_value_cents": 1990,
            "daypart_epoch": 0,
            "logged_by_user_id": H.ASSOCIATE_1_USER_ID,
        },
    )

    after_store = X.read_store(api, store["id"])
    assert after_store["waste_cost_cents_mtd"] == 400
    assert after_store["hot_case_slots_used"] == 1
    assert X.read_readiness(api, store["id"])["retail_waste_exposure_cents"] == 1990


def test_the_daypart_sweep_spares_a_pan_with_units_reserved_to_an_order(api):
    """Both sweep conditions hold, and the reservation still saves the pan.

    The sweep runs "for every batch of that store which is currently in
    `HOLDING` and has a `reserved_qty` of zero", and this pan fails that test
    because placement moved units across: "the selected batch is recorded on the
    line as its `fulfillment_batch_id`, the line's `reserved_qty` is set to the
    line's `qty`, and on the batch the same quantity is subtracted from
    `remaining_qty` and added to `reserved_qty`". So although its hold has
    expired and the new menu excludes the item, "Batches carrying reservations
    are left in `HOLDING` and are not swept." Nothing is written off, so the
    store's slot and waste counters do not move.

    Design: Corner/state_machines/daypart_sweep_spares_a_holding_batch_that_still_has_reserved_units
    """
    X.set_clock(api, CLOCK_EARLY)
    store = X.create_store(api)
    X.create_published_plan(api, store["id"], daypart="BREAKFAST")
    unit = X.create_bakery_case(api, store["id"], slot_count=3)
    pretzel = X.create_pretzel(api, valid_dayparts=["BREAKFAST"])
    coffee = X.create_coffee(api)
    batch = X.create_holding_batch(
        api, store["id"], pretzel["id"], unit["id"],
        slot_index=1, planned_qty=40, bake_start_at=BAKE_START,
    )
    order = X.create_draft_order(api, store["id"])
    pretzel_line = X.add_order_line(api, order["id"], pretzel["id"], 12)
    X.add_order_line(api, order["id"], coffee["id"], 1)
    placed = X.place_order(api, order["id"])
    assert placed["production_status"] == "PLACED"
    X.set_clock(api, CLOCK_LUNCH)

    after_store = H.get_success_data(
        api.create_daypart_transition(
            store["id"], F.daypart_transition_payload("LUNCH"), H.STORE_MANAGER_HEADERS
        ),
        200,
    )

    assert after_store["current_daypart"] == "LUNCH"
    assert after_store["daypart_epoch"] == 1
    assert after_store["waste_cost_cents_mtd"] == 0
    assert after_store["hot_case_slots_used"] == 1

    spared = X.read_batch(api, batch["id"])
    assert spared["status"] == "HOLDING"
    assert spared["remaining_qty"] == 28
    assert spared["reserved_qty"] == 12
    assert spared["discarded_qty"] == 0

    line = X.read_order_line(api, pretzel_line["id"])
    assert line["reserved_qty"] == 12
    assert line["fulfillment_batch_id"] == batch["id"]

    rows, meta = H.validate_paginated(
        api.list_batch_waste_logs(batch["id"], H.STORE_MANAGER_HEADERS)
    )
    assert meta["total_count"] == 0
    assert rows == []
