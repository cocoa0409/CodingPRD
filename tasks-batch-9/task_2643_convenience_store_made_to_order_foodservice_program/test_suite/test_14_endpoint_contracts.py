"""What each endpoint promises to return, write and leave alone.

A delete answers with no body, so its recomputation has to be read back; a
suspend touches one column and the version; a daypart flip is a bulk sweep
with skip-not-fail semantics; a nested create must refuse an orphan; a queue
read must order and filter; and a release is legal only inside its window.
"""

import test_helpers as H
from test_helpers import factories as F
from test_helpers import fixtures as X

CLOCK_EARLY = "2026-08-01T06:00:00Z"
CLOCK_LUNCH = "2026-08-01T11:00:00Z"
CLOCK_BEFORE_WINDOW = "2026-08-01T11:05:00Z"
WINDOW_OPENS = "2026-08-01T13:00:00Z"
WINDOW_CLOSES = "2026-08-01T13:30:00Z"
FUEL_AT = "2026-08-01T09:15:00Z"


def test_removing_a_draft_line_reprices_the_order_and_counts_as_a_write(api):
    """The 204 carries nothing, so the subtotal is read back at 899.

    "Removing a line addresses it by its `line_id` in the path and returns no
    body", and the recomputation is the same one an add performs: "Adding a
    line, and equally removing one, recomputes the order's
    `subtotal_gross_cents` as the sum of the `line_gross_cents` of all its
    remaining lines and increments the order's `version` by one." Four writes
    have therefore touched this order. The removed row is gone for good, since
    "a `line_id` that resolves to nothing, or that resolves to a line belonging
    to a different order, reports `ERR_ORDER_LINE_NOT_FOUND`".

    Design: Corner/endpoints/deleting_a_draft_order_line_recomputes_the_subtotal
    """
    store = X.create_store(api)
    hoagie = X.create_hoagie(api)
    coffee = X.create_coffee(api)
    order = X.create_draft_order(api, store["id"])
    hoagie_line = X.add_order_line(api, order["id"], hoagie["id"], 1)
    coffee_line = X.add_order_line(api, order["id"], coffee["id"], 1)
    assert coffee_line["line_gross_cents"] == 249
    assert X.read_order(api, order["id"])["subtotal_gross_cents"] == 1148

    response = api.delete_order_line(order["id"], coffee_line["id"], H.STORE_TERMINAL_HEADERS)

    H.assert_no_content(response)
    after = X.read_order(api, order["id"])
    assert after["subtotal_gross_cents"] == 899
    assert after["version"] == 4

    _, meta = H.validate_paginated(
        api.list_order_lines(H.STORE_MANAGER_HEADERS, {"order_id": order["id"]})
    )
    assert meta["total_count"] == 1
    assert X.read_order_line(api, hoagie_line["id"])["line_gross_cents"] == 899
    H.validate_error(
        api.get_order_line(coffee_line["id"], H.STORE_MANAGER_HEADERS),
        H.ApiErrorId.ERR_ORDER_LINE_NOT_FOUND.value,
        404,
    )


def test_suspending_a_rule_moves_only_its_status_and_its_version(api):
    """ACTIVE becomes SUSPENDED at version 2, pricing untouched.

    "A rule opens in the `ACTIVE` status and only active rules ever enter the
    candidate pool. A `ChainAdmin` may suspend a rule, moving its `status` to
    `SUSPENDED`". Suspension is not a repricing: the flat discount and the
    tie-break rank are exactly as configured, where "`stacking_rank`, an
    integer of at least 1, is the first tie-break when two rules produce the
    same discount, and a lower rank wins". The version moves because it carries
    "`version`, an integer that starts at 1 on creation and increments by
    exactly one on every mutation", and the status filter now sorts the rule the
    other way, since "The rule list may be filtered by `status` and by `kind`."

    Design: Corner/endpoints/suspend_promotion_rule_flips_status_and_bumps_version
    """
    rule = H.get_success_data(
        api.create_promotion_rule(
            F.cents_off_promotion_payload(
                code="BUNDLE100", discount_cents=100, max_discount_cents=100, stacking_rank=9
            ),
            H.CHAIN_ADMIN_HEADERS,
        ),
        201,
    )
    assert rule["status"] == "ACTIVE"
    assert rule["version"] == 1

    suspended = H.get_success_data(
        api.suspend_promotion_rule(rule["id"], {}, H.CHAIN_ADMIN_HEADERS), 200
    )

    assert suspended["status"] == "SUSPENDED"
    assert suspended["version"] == 2
    assert suspended["discount_cents"] == 100
    assert suspended["stacking_rank"] == 9

    _, suspended_meta = H.validate_paginated(
        api.list_promotion_rules(H.CHAIN_ADMIN_HEADERS, {"status": "SUSPENDED"})
    )
    _, active_meta = H.validate_paginated(
        api.list_promotion_rules(H.CHAIN_ADMIN_HEADERS, {"status": "ACTIVE"})
    )
    assert suspended_meta["total_count"] == 1
    assert active_meta["total_count"] == 0


def test_one_daypart_flip_sweeps_both_holding_pans_and_spares_the_planned_one(api):
    """A bulk write-off that skips rather than fails on the cold pan.

    "for every batch of that store which is currently in `HOLDING` and has a
    `reserved_qty` of zero, writes it off entirely when either of two
    conditions holds: its `hold_expires_at` is at or before the logical clock,
    or the menu item's `valid_dayparts` does not include the newly current
    daypart." Both pulled pans match on both counts; the never-baked pan is not
    in `HOLDING` and is left alone. Each swept pan "adds its food-cost
    valuation to the store's `waste_cost_cents_mtd`, decrements the store's
    `hot_case_slots_used` by one", and the inspection summary reads the other
    basis, where "The `retail_waste_exposure_cents` figure sums the
    `retail_value_cents` of every waste record belonging to the store's
    batches."

    Design: Corner/endpoints/daypart_transition_sweeps_two_batches_and_skips_the_planned_one
    """
    X.set_clock(api, CLOCK_EARLY)
    store = X.create_store(api)
    unit = X.create_bakery_case(api, store["id"], slot_count=3)
    pretzel = X.create_pretzel(api, valid_dayparts=["BREAKFAST"])
    forty = X.create_holding_batch(
        api, store["id"], pretzel["id"], unit["id"],
        slot_index=1, planned_qty=40, bake_start_at=CLOCK_EARLY,
    )
    twenty = X.create_holding_batch(
        api, store["id"], pretzel["id"], unit["id"],
        slot_index=2, planned_qty=20, bake_start_at=CLOCK_EARLY,
    )
    never_baked = X.create_planned_batch(
        api, store["id"], pretzel["id"], unit["id"],
        slot_index=3, planned_qty=30, bake_start_at=CLOCK_EARLY,
    )
    X.set_clock(api, CLOCK_LUNCH)

    swept = X.transition_daypart(api, store["id"], "LUNCH")

    assert swept["current_daypart"] == "LUNCH"
    assert swept["waste_cost_cents_mtd"] == 2400
    assert swept["hot_case_slots_used"] == 0

    first = X.read_batch(api, forty["id"])
    second = X.read_batch(api, twenty["id"])
    cold = X.read_batch(api, never_baked["id"])
    assert first["status"] == "DISCARDED"
    assert first["discarded_qty"] == 40
    assert second["status"] == "DISCARDED"
    assert second["discarded_qty"] == 20
    assert cold["status"] == "PLANNED"
    assert cold["baked_qty"] == 0
    assert cold["discarded_qty"] == 0

    for batch, expected in ((forty, 1), (twenty, 1), (never_baked, 0)):
        _, meta = H.validate_paginated(
            api.list_batch_waste_logs(batch["id"], H.STORE_MANAGER_HEADERS)
        )
        assert meta["total_count"] == expected

    _, discarded_meta = H.validate_paginated(
        api.list_production_batches(
            H.KITCHEN_ASSOCIATE_HEADERS, {"store_id": store["id"], "status": "DISCARDED"}
        )
    )
    assert discarded_meta["total_count"] == 2

    readiness = X.read_readiness(api, store["id"])
    assert readiness["retail_waste_exposure_cents"] == 11940
    assert readiness["food_cost_waste_cents_mtd"] == 2400


def test_a_fuel_sale_belongs_to_its_member_and_cannot_be_orphaned(api):
    """The same body is a 201 under a real member and a 404 under a stranger.

    "Fuel transactions, like modifier options, are immutable evidence and carry
    no `updated_at` and no `version`; each one references its owner through
    `loyalty_account_id`", and "A member's fuel sales are listable." The
    unknown owner is caught by path resolution, where "The first identifier in
    the path that resolves to nothing produces its own 404" including
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, so no orphan row appears on anyone's list.
    The stored spend is the posted arithmetic: "The system computes
    `fuel_spend_cents` as the gallons multiplied by the posted price per
    gallon, rounded half up to whole cents."

    Design: Corner/endpoints/fuel_transaction_links_to_its_loyalty_account_and_is_listable
    """
    first_member = X.create_loyalty_account(api, member_code="M-1", email="m1@example.com")
    second_member = X.create_loyalty_account(api, member_code="M-2", email="m2@example.com")
    payload = F.fuel_transaction_payload(gallons=12.5, occurred_at=FUEL_AT)

    fuel = H.get_success_data(
        api.create_fuel_transaction(first_member["id"], payload, H.STORE_TERMINAL_HEADERS), 201
    )

    assert fuel["loyalty_account_id"] == first_member["id"]
    assert fuel["fuel_spend_cents"] == 4113
    H.assert_append_only_record(fuel)

    orphan = api.create_fuel_transaction(H.NON_EXISTENT_UUID, payload, H.STORE_TERMINAL_HEADERS)

    H.validate_error(orphan, H.ApiErrorId.ERR_LOYALTY_ACCOUNT_NOT_FOUND.value, 404)

    rows, meta = H.validate_paginated(
        api.list_fuel_transactions(first_member["id"], H.STORE_TERMINAL_HEADERS)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == fuel["id"]
    _, empty_meta = H.validate_paginated(
        api.list_fuel_transactions(second_member["id"], H.STORE_TERMINAL_HEADERS)
    )
    assert empty_meta["total_count"] == 0


def test_the_queue_read_is_ordered_by_position_and_narrowed_by_station(api):
    """Four tickets, two stations, two independent numberings.

    "A store's make-line queue is read per station and returned ordered by
    `sequence_position` and then by `created_at`, with optional filters on
    `station` and `status`." Each station keeps its own counter, because "The
    queue a new ticket joins consists of the tickets of the same `store_id` and
    the same `station` whose `status` is `QUEUED` or `IN_PROGRESS`" and the new
    position "is one more than the number of tickets already in that queue,
    counted **before** the new ticket is inserted"; the second order therefore
    numbers 2 at both stations rather than 3 and 4. Waiting time follows the
    same partition, since "Its `lead_seconds` is the sum of the `prep_seconds`
    of exactly those tickets ahead of it": 180 behind the hoagie and 45 behind
    the coffee, whose promise is "the current logical-clock instant advanced by
    its `lead_seconds` and then by its own `prep_seconds`".

    Design: Corner/endpoints/kitchen_queue_read_filters_by_station_and_orders_by_sequence
    """
    store = X.setup_store_open_for_lunch(api, clock=CLOCK_LUNCH)
    hoagie = X.create_hoagie(api)
    coffee = X.create_coffee(api)
    for _ in range(2):
        order = X.create_draft_order(api, store["id"])
        X.add_order_line(api, order["id"], hoagie["id"], 1)
        X.add_order_line(api, order["id"], coffee["id"], 1)
        X.place_order(api, order["id"])

    sandwich, sandwich_meta = H.validate_paginated(
        api.get_store_kitchen_queue(
            store["id"], H.KITCHEN_ASSOCIATE_HEADERS, {"station": "SANDWICH"}
        )
    )
    assert sandwich_meta["total_count"] == 2
    assert sandwich_meta["has_more"] is False
    assert sandwich[0]["sequence_position"] == 1
    assert sandwich[0]["lead_seconds"] == 0
    assert sandwich[1]["sequence_position"] == 2
    assert sandwich[1]["lead_seconds"] == 180

    beverage, beverage_meta = H.validate_paginated(
        api.get_store_kitchen_queue(
            store["id"], H.KITCHEN_ASSOCIATE_HEADERS, {"station": "BEVERAGE"}
        )
    )
    assert beverage_meta["total_count"] == 2
    assert beverage_meta["has_more"] is False
    assert beverage[0]["lead_seconds"] == 0
    assert beverage[1]["lead_seconds"] == 45
    assert beverage[1]["promised_ready_at"] == "2026-08-01T11:01:30Z"

    everything, all_meta = H.validate_paginated(
        api.get_store_kitchen_queue(store["id"], H.SHIFT_LEAD_HEADERS)
    )
    assert all_meta["total_count"] == 4
    assert all_meta["has_more"] is False
    assert [ticket["sequence_position"] for ticket in everything] == [1, 1, 2, 2]

    _, hot_food_meta = H.validate_paginated(
        api.get_store_kitchen_queue(
            store["id"], H.KITCHEN_ASSOCIATE_HEADERS, {"station": "HOT_FOOD"}
        )
    )
    assert hot_food_meta["total_count"] == 0


def test_a_preorder_cannot_be_released_before_its_window_opens(api):
    """Assembled at 11:05 is not releasable; 13:00 exactly is.

    A finished make line does not free a pre-order, because the gate reads the
    channel: "An order entering `ASSEMBLED` advances immediately to `READY` when
    either the `channel` is `TOUCHSCREEN`, or the current logical clock has
    reached the order's `pickup_window_start`. A pre-order or catering order
    that is assembled ahead of its window therefore *stays* in `ASSEMBLED`".
    The manual path carries the same clock condition: "the current logical clock
    must have reached the order's `pickup_window_start`, otherwise
    `ERR_PICKUP_WINDOW_NOT_OPEN` (HTTP 409)". Reaching the boundary satisfies
    it, and "On entering `READY` the order's `ready_at` is set to the current
    logical-clock instant". The money axis is untouched by any of this, since
    "The settlement axis begins at `UNPAID`, and the only thing it ever reads on
    the production axis is enough to exclude a voided order."

    Design: Corner/endpoints/release_before_the_pickup_window_opens_is_rejected
    """
    store = X.setup_store_open_for_lunch(api, clock=CLOCK_LUNCH)
    coffee = X.create_coffee(api)
    order = X.create_draft_preorder(api, store["id"], WINDOW_OPENS, WINDOW_CLOSES)
    X.add_order_line(api, order["id"], coffee["id"], 1)
    X.place_order(api, order["id"])
    X.authorize_order(api, order["id"], "APP_WALLET")
    ticket = X.find_ticket(api, order["id"], "BEVERAGE")
    X.work_ticket_to_done(api, ticket["id"])
    X.set_clock(api, CLOCK_BEFORE_WINDOW)

    assembled = X.read_order(api, order["id"])
    assert assembled["production_status"] == "ASSEMBLED"
    assert assembled["ready_at"] is None

    too_early = api.release_order(order["id"], {}, H.STORE_MANAGER_HEADERS)

    H.validate_error(too_early, H.ApiErrorId.ERR_PICKUP_WINDOW_NOT_OPEN.value, 409)
    still_waiting = X.read_order(api, order["id"])
    assert still_waiting["production_status"] == "ASSEMBLED"
    assert still_waiting["ready_at"] is None

    X.set_clock(api, WINDOW_OPENS)
    released = H.get_success_data(
        api.release_order(order["id"], {}, H.STORE_MANAGER_HEADERS), 200
    )

    assert released["production_status"] == "READY"
    assert released["ready_at"] == WINDOW_OPENS
    assert released["settlement_status"] == "AUTHORIZED"
    finished = H.get_success_data(
        api.get_kitchen_ticket(ticket["id"], H.KITCHEN_ASSOCIATE_HEADERS)
    )
    assert finished["status"] == "DONE"
