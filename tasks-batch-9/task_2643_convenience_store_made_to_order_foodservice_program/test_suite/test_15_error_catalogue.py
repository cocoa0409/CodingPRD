"""Reachability of the published error catalogue.

Each family is exercised as a family, because the interesting failure is not
that an id is missing but that two ids have been collapsed into one: a shared
"not found", a global unique index where the scope is narrower, one generic
"wrong state" in place of four, or a window code that ignores the channel.
"""

import test_helpers as H
from test_helpers import factories as F
from test_helpers import fixtures as X

E = H.ApiErrorId
MISSING = H.NON_EXISTENT_UUID

CLOCK_EARLY = "2026-08-01T06:00:00Z"
CLOCK_LUNCH = "2026-08-01T11:00:00Z"
HOLD_EXPIRY = "2026-08-01T10:00:00Z"
CATERING_WINDOW = ("2026-08-01T23:00:00Z", "2026-08-01T23:30:00Z")


def test_each_missing_entity_answers_with_its_own_not_found_id(api):
    """Eleven unknown ids, eleven distinct 404s.

    "The first identifier in the path that resolves to nothing produces its own
    404: `ERR_STORE_NOT_FOUND`, `ERR_HOLDING_UNIT_NOT_FOUND`,
    `ERR_MENU_ITEM_NOT_FOUND`, `ERR_LOYALTY_ACCOUNT_NOT_FOUND`,
    `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`,
    `ERR_KITCHEN_TICKET_NOT_FOUND`, `ERR_PRODUCTION_BATCH_NOT_FOUND`,
    `ERR_CORRECTIVE_ACTION_NOT_FOUND`, `ERR_STAFFING_PLAN_NOT_FOUND` or
    `ERR_PROMOTION_RULE_NOT_FOUND`." Two of the ids have no path of their own
    and are reachable only through a body reference, because the step for
    "Foreign keys carried in the request body, resolved in the order the fields
    are declared in the endpoint's input list" covers "line creation,
    production-batch creation and corrective-action creation, and may yield
    `ERR_STORE_NOT_FOUND`, `ERR_MENU_ITEM_NOT_FOUND`,
    `ERR_MODIFIER_OPTION_NOT_FOUND`, `ERR_HOLDING_UNIT_NOT_FOUND`,
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND` or `ERR_TEMPERATURE_LOG_NOT_FOUND`". A
    rejected line leaves the draft alone,
    because a line only ever "recomputes the order's `subtotal_gross_cents` as
    the sum of the `line_gross_cents` of all its remaining lines".

    Design: Corner/errors/every_not_found_error_id_is_reachable_with_an_unknown_id
    """
    store = X.create_store(api)
    hoagie = X.create_hoagie(api)
    order = X.create_draft_order(api, store["id"])

    attempts = [
        (api.get_store(MISSING, H.CHAIN_ADMIN_HEADERS), E.ERR_STORE_NOT_FOUND),
        (api.get_holding_unit(MISSING, H.STORE_MANAGER_HEADERS), E.ERR_HOLDING_UNIT_NOT_FOUND),
        (
            api.suspend_promotion_rule(MISSING, {}, H.CHAIN_ADMIN_HEADERS),
            E.ERR_PROMOTION_RULE_NOT_FOUND,
        ),
        (
            api.publish_staffing_plan(MISSING, {}, H.STORE_MANAGER_HEADERS),
            E.ERR_STAFFING_PLAN_NOT_FOUND,
        ),
        (
            api.get_production_batch(MISSING, H.KITCHEN_ASSOCIATE_HEADERS),
            E.ERR_PRODUCTION_BATCH_NOT_FOUND,
        ),
        (api.get_order(MISSING, H.STORE_MANAGER_HEADERS), E.ERR_ORDER_NOT_FOUND),
        (api.get_order_line(MISSING, H.STORE_TERMINAL_HEADERS), E.ERR_ORDER_LINE_NOT_FOUND),
        (
            api.get_kitchen_ticket(MISSING, H.KITCHEN_ASSOCIATE_HEADERS),
            E.ERR_KITCHEN_TICKET_NOT_FOUND,
        ),
        (
            api.get_corrective_action(MISSING, H.SHIFT_LEAD_HEADERS),
            E.ERR_CORRECTIVE_ACTION_NOT_FOUND,
        ),
        (
            api.create_corrective_action(
                F.corrective_action_payload(MISSING, "Reset breaker"), H.SHIFT_LEAD_HEADERS
            ),
            E.ERR_TEMPERATURE_LOG_NOT_FOUND,
        ),
        (
            api.create_order_line(
                order["id"],
                F.order_line_payload(hoagie["id"], 1, [F.modifier_selection(MISSING, 1)]),
                H.STORE_TERMINAL_HEADERS,
            ),
            E.ERR_MODIFIER_OPTION_NOT_FOUND,
        ),
    ]
    for response, expected in attempts:
        H.validate_error(response, expected.value, 404)

    assert X.read_order(api, order["id"])["subtotal_gross_cents"] == 0
    _, meta = H.validate_paginated(
        api.list_order_lines(H.STORE_MANAGER_HEADERS, {"order_id": order["id"]})
    )
    assert meta["total_count"] == 0


def test_one_duplicate_code_id_serves_six_scopes_two_of_them_narrow(api):
    """BC-1 collides in its own store and is free in the next one.

    Four scopes are chain-wide: the `store_code` "must be unique across the
    chain", a menu item has "a chain-unique `sku` (a collision reports
    `ERR_DUPLICATE_CODE`)", a promotion rule "a chain-unique `code` (collisions
    report `ERR_DUPLICATE_CODE`)" and a member "a chain-unique `member_code`".
    Two are narrower: a modifier option "carries a `code` that must be unique
    within that menu item", and a holding unit is "described by a `unit_code`
    that must be unique within its store — a collision again reports
    `ERR_DUPLICATE_CODE`". Re-using BC-1 beneath a second store therefore has to
    succeed, and the created unit records the site it belongs to, since "The
    unit's own `store_id` records the site it lives in."

    Design: Corner/errors/duplicate_codes_collide_across_every_coded_entity
    """
    first_store = X.create_store(api)
    second_store = X.create_store(
        api, store_code="WAWA-0102", name="Wawa Route 9", is_fuel_site=False
    )
    X.create_bakery_case(api, first_store["id"])
    hoagie = X.create_hoagie(api)
    X.create_modifier_option(
        api, hoagie["id"], code="EXTRA-PROV", price_delta_cents=60, is_premium=True
    )
    X.create_promotion_rule(api, code="BUNDLE100")
    X.create_loyalty_account(api, member_code="M-1", email="m1@example.com")

    collisions = [
        api.create_store(
            F.store_payload(name="Wawa Route 1 Duplicate"), H.CHAIN_ADMIN_HEADERS
        ),
        api.create_menu_item(
            F.menu_item_payload(name="Italian Hoagie Clone", base_price_cents=999),
            H.CHAIN_ADMIN_HEADERS,
        ),
        api.create_modifier_option(
            hoagie["id"],
            F.modifier_option_payload(modifier_class="TOPPING", price_delta_cents=10),
            H.CHAIN_ADMIN_HEADERS,
        ),
        api.create_promotion_rule(
            F.promotion_rule_payload(code="BUNDLE100", valid_dayparts=["DINNER"], stacking_rank=3),
            H.CHAIN_ADMIN_HEADERS,
        ),
        api.create_loyalty_account(
            F.loyalty_account_payload(member_code="M-1", email="other@example.com"),
            H.CHAIN_ADMIN_HEADERS,
        ),
        api.create_holding_unit(
            first_store["id"],
            F.holding_unit_payload(unit_type="HOT_CASE", min_temp_f=140, max_temp_f=190),
            H.STORE_MANAGER_HEADERS,
        ),
    ]
    for response in collisions:
        H.validate_error(response, E.ERR_DUPLICATE_CODE.value, 409)

    twin = H.get_success_data(
        api.create_holding_unit(
            second_store["id"], F.holding_unit_payload(), H.STORE_MANAGER_HEADERS
        ),
        201,
    )
    assert twin["unit_code"] == "BC-1"
    assert twin["store_id"] == second_store["id"]

    for store_id in (first_store["id"], second_store["id"]):
        _, meta = H.validate_paginated(
            api.list_store_holding_units(store_id, H.STORE_MANAGER_HEADERS)
        )
        assert meta["total_count"] == 1
    _, option_meta = H.validate_paginated(
        api.list_modifier_options(hoagie["id"], H.CHAIN_ADMIN_HEADERS)
    )
    assert option_meta["total_count"] == 1


def test_one_order_yields_four_different_wrong_state_ids(api):
    """Settlement, production, ticket and rework each answer in their own code.

    Step 11 of the pipeline enumerates them: "State-transition legality on every
    state-transition endpoint — `ERR_ORDER_NOT_DRAFT`,
    `ERR_ORDER_PRODUCTION_STATE_INVALID`, `ERR_ORDER_SETTLEMENT_STATE_INVALID`,
    `ERR_ORDER_NOT_REWORKABLE`, `ERR_TICKET_STATE_INVALID`". Settling needs
    tender first, because "The `settlement_status` must be `AUTHORIZED`,
    otherwise `ERR_ORDER_SETTLEMENT_STATE_INVALID`"; hand-off needs a finished
    order, because "The order's `production_status` must be `READY`, otherwise
    `ERR_ORDER_PRODUCTION_STATE_INVALID`"; and finishing an unclaimed ticket is
    a ticket-state fault, since "the same code covers completing a ticket that
    is not in progress". The last refusal proves the rework gate reads the order
    rather than the ticket: the ticket is `DONE` and reopenable in itself, but
    "the owning order's `production_status` must be `IN_PRODUCTION` or
    `ASSEMBLED`, so an order already picked up or voided is not reworkable and
    reports `ERR_ORDER_NOT_REWORKABLE` (HTTP 409)".

    Design: Corner/errors/order_lifecycle_rejections_cover_the_state_error_ids
    """
    store = X.setup_store_open_for_lunch(api, clock=CLOCK_LUNCH)
    coffee = X.create_coffee(api)
    empty = X.create_draft_order(api, store["id"])
    order = X.create_draft_order(api, store["id"])
    X.add_order_line(api, order["id"], coffee["id"], 1)

    H.validate_error(
        api.place_order(empty["id"], {}, H.STORE_TERMINAL_HEADERS), E.ERR_ORDER_EMPTY.value, 422
    )
    H.validate_error(
        api.settle_order(order["id"], {}, H.STORE_TERMINAL_HEADERS),
        E.ERR_ORDER_SETTLEMENT_STATE_INVALID.value,
        409,
    )

    assert X.place_order(api, order["id"])["production_status"] == "PLACED"
    H.validate_error(
        api.pickup_order(order["id"], {}, H.STORE_TERMINAL_HEADERS),
        E.ERR_ORDER_PRODUCTION_STATE_INVALID.value,
        409,
    )

    ticket = X.find_ticket(api, order["id"], "BEVERAGE")
    H.validate_error(
        api.complete_kitchen_ticket(ticket["id"], {}, H.KITCHEN_ASSOCIATE_HEADERS),
        E.ERR_TICKET_STATE_INVALID.value,
        409,
    )

    X.authorize_order(api, order["id"])
    X.start_ticket(api, ticket["id"])
    assert X.complete_ticket(api, ticket["id"])["status"] == "DONE"

    H.validate_error(
        api.reopen_kitchen_ticket(
            ticket["id"], F.reopen_payload("Customer asked for a remake"), H.SHIFT_LEAD_HEADERS
        ),
        E.ERR_ORDER_NOT_REWORKABLE.value,
        409,
    )

    assert X.read_order(api, empty["id"])["production_status"] == "DRAFT"
    finished = X.read_order(api, order["id"])
    assert finished["production_status"] == "READY"
    assert finished["settlement_status"] == "AUTHORIZED"
    untouched = H.get_success_data(
        api.get_kitchen_ticket(ticket["id"], H.KITCHEN_ASSOCIATE_HEADERS)
    )
    assert untouched["rework_count"] == 0
    assert X.read_store(api, store["id"])["rework_waste_cents_mtd"] == 0


def test_an_expired_hold_outranks_the_supply_shortfall_it_also_causes(api):
    """No pan at all is a supply fault; a stale pan is a safety fault.

    With nothing in the case "every `PAR_BAKED_CASE` line must be coverable by
    an available batch; if the stock selector finds none, the commit is refused
    with `ERR_INSUFFICIENT_BATCH_QTY` (HTTP 422), and a line pointed at a batch
    whose hold has already expired reports `ERR_BATCH_HOLD_EXPIRED` (HTTP 422)".
    Once the only pan has gone stale both rules bite, and the tie-break is fixed
    by "the domain rules in exactly this order", which places
    `ERR_BATCH_HOLD_EXPIRED` well ahead of `ERR_INSUFFICIENT_BATCH_QTY`. The
    boundary is inclusive: the pull "sets `hold_started_at` to the current
    logical-clock instant and `hold_expires_at` to that instant advanced by the
    item's `hold_minutes`; a batch at or past its `hold_expires_at` may no longer
    fulfil order lines." The same chain shows the sensor band is the probe's own,
    "between minus 40 and 250 degrees Fahrenheit inclusive", not the cabinet's.

    Design: Corner/errors/production_rejections_cover_the_batch_and_unit_error_ids
    """
    X.set_clock(api, CLOCK_EARLY)
    store = X.create_store(api)
    X.create_published_plan(api, store["id"], daypart="BREAKFAST")
    unit = X.create_bakery_case(api, store["id"])
    pretzel = X.create_pretzel(api)
    coffee = X.create_coffee(api)
    first_order = X.create_draft_order(api, store["id"])
    X.add_order_line(api, first_order["id"], pretzel["id"], 5)
    second_order = X.create_draft_order(api, store["id"])
    X.add_order_line(api, second_order["id"], pretzel["id"], 5)

    H.validate_error(
        api.create_production_batch(
            F.production_batch_payload(
                store["id"], coffee["id"], unit["id"], planned_qty=10, bake_start_at=CLOCK_EARLY
            ),
            H.KITCHEN_ASSOCIATE_HEADERS,
        ),
        E.ERR_ITEM_NOT_PAR_BAKED.value,
        422,
    )
    H.validate_error(
        api.create_production_batch(
            F.production_batch_payload(
                store["id"],
                pretzel["id"],
                unit["id"],
                slot_index=9,
                planned_qty=10,
                bake_start_at=CLOCK_EARLY,
            ),
            H.KITCHEN_ASSOCIATE_HEADERS,
        ),
        E.ERR_SLOT_INDEX_OUT_OF_RANGE.value,
        422,
    )
    H.validate_error(
        api.place_order(first_order["id"], {}, H.STORE_TERMINAL_HEADERS),
        E.ERR_INSUFFICIENT_BATCH_QTY.value,
        422,
    )

    batch = X.create_holding_batch(
        api, store["id"], pretzel["id"], unit["id"], planned_qty=40, bake_start_at=CLOCK_EARLY
    )
    assert batch["hold_expires_at"] == HOLD_EXPIRY

    H.validate_error(
        api.discard_production_batch(
            batch["id"],
            F.discard_payload(99, "QUALITY_REJECT", batch["version"]),
            H.SHIFT_LEAD_HEADERS,
        ),
        E.ERR_DISCARD_QTY_EXCEEDS_REMAINING.value,
        422,
    )
    H.validate_error(
        api.create_temperature_log(
            unit["id"], F.temperature_log_payload(900), H.KITCHEN_ASSOCIATE_HEADERS
        ),
        E.ERR_TEMP_READING_OUT_OF_SENSOR_RANGE.value,
        422,
    )

    X.set_clock(api, HOLD_EXPIRY)
    H.validate_error(
        api.place_order(second_order["id"], {}, H.STORE_TERMINAL_HEADERS),
        E.ERR_BATCH_HOLD_EXPIRED.value,
        422,
    )

    assert X.read_order(api, first_order["id"])["production_status"] == "DRAFT"
    assert X.read_order(api, second_order["id"])["production_status"] == "DRAFT"
    survivor = X.read_batch(api, batch["id"])
    assert survivor["status"] == "HOLDING"
    assert survivor["remaining_qty"] == 40
    assert survivor["reserved_qty"] == 0
    probe = X.read_holding_unit(api, unit["id"])
    assert probe["status"] == "OPERATIONAL"
    assert probe["consecutive_out_of_range_count"] == 0

    _, log_meta = H.validate_paginated(
        api.list_temperature_logs(unit["id"], H.KITCHEN_ASSOCIATE_HEADERS)
    )
    assert log_meta["total_count"] == 0
    _, batch_meta = H.validate_paginated(
        api.list_production_batches(H.KITCHEN_ASSOCIATE_HEADERS, {"store_id": store["id"]})
    )
    assert batch_meta["total_count"] == 1


def test_the_window_and_catering_refusals_stay_three_and_two_separate_ids(api):
    """Each channel earns its own window code, at creation and at commit.

    "A `TOUCHSCREEN` order must carry neither bound; supplying either one is
    rejected with `ERR_PICKUP_WINDOW_NOT_ALLOWED` (HTTP 422). A
    `MOBILE_PREORDER` or `CATERING` order must carry both; omitting either is
    rejected with `ERR_PICKUP_WINDOW_REQUIRED` (HTTP 422). Where both are
    present, the `pickup_window_end` must be strictly after the
    `pickup_window_start`, and a window that is not strictly ordered is rejected
    with `ERR_PICKUP_WINDOW_INVALID` (HTTP 422)." The catering pair splits across
    two endpoints because only one of the two is knowable while the basket is
    still being built: eligibility is "checked both at line-add time and again at
    commit time", whereas the money floor needs a finished basket — "the order's
    `subtotal_gross_cents` must reach at least 5000 cents, otherwise
    `ERR_ORDER_MINIMUM_NOT_MET` (HTTP 422)". A modifier taken five deep breaks
    its own ceiling, since "each modifier entry's `qty` must be at least 1 and
    must not exceed that option's `max_qty`".

    Design: Corner/errors/order_intake_rejections_cover_the_window_and_catering_error_ids
    """
    store = X.setup_store_open_for_lunch(api, clock=CLOCK_LUNCH)
    hoagie = X.create_hoagie(api)
    provolone = X.create_modifier_option(
        api, hoagie["id"], price_delta_cents=60, is_premium=True, max_qty=1
    )
    coffee = X.create_coffee(api, is_catering_eligible=False)
    catering = X.create_draft_catering_order(api, store["id"], *CATERING_WINDOW)

    H.validate_error(
        api.create_order(
            F.order_payload(
                store["id"],
                pickup_window_start=CATERING_WINDOW[0],
                pickup_window_end=CATERING_WINDOW[1],
            ),
            H.STORE_TERMINAL_HEADERS,
        ),
        E.ERR_PICKUP_WINDOW_NOT_ALLOWED.value,
        422,
    )
    H.validate_error(
        api.create_order(
            F.order_payload(store["id"], channel="MOBILE_PREORDER"), H.STORE_TERMINAL_HEADERS
        ),
        E.ERR_PICKUP_WINDOW_REQUIRED.value,
        422,
    )
    H.validate_error(
        api.create_order(
            F.catering_order_payload(store["id"], CATERING_WINDOW[0], CATERING_WINDOW[0]),
            H.STORE_TERMINAL_HEADERS,
        ),
        E.ERR_PICKUP_WINDOW_INVALID.value,
        422,
    )
    H.validate_error(
        api.create_order_line(
            catering["id"], F.order_line_payload(coffee["id"], 1), H.STORE_TERMINAL_HEADERS
        ),
        E.ERR_ITEM_NOT_CATERING_ELIGIBLE.value,
        422,
    )
    H.validate_error(
        api.create_order_line(
            catering["id"],
            F.order_line_payload(hoagie["id"], 1, [F.modifier_selection(provolone["id"], 5)]),
            H.STORE_TERMINAL_HEADERS,
        ),
        E.ERR_MODIFIER_LIMIT_EXCEEDED.value,
        422,
    )

    accepted = X.add_order_line(api, catering["id"], hoagie["id"], 1)
    assert accepted["line_gross_cents"] == 899

    H.validate_error(
        api.place_order(catering["id"], {}, H.STORE_TERMINAL_HEADERS),
        E.ERR_ORDER_MINIMUM_NOT_MET.value,
        422,
    )

    unsent = X.read_order(api, catering["id"])
    assert unsent["subtotal_gross_cents"] == 899
    assert unsent["production_status"] == "DRAFT"
    _, line_meta = H.validate_paginated(
        api.list_order_lines(H.STORE_MANAGER_HEADERS, {"order_id": catering["id"]})
    )
    assert line_meta["total_count"] == 1
    _, order_meta = H.validate_paginated(
        api.list_orders(H.STORE_MANAGER_HEADERS, {"store_id": store["id"]})
    )
    assert order_meta["total_count"] == 1


def test_the_platform_guards_refuse_a_locked_plan_a_skip_a_rewind_and_an_overdraft(api):
    """Four whole-platform refusals, none of which mutates anything.

    A locked plan is not superseded but rejected: "If the incumbent has already
    been locked, however, the new plan is refused outright with `ERR_PLAN_LOCKED`
    (HTTP 409) and nothing is superseded." A legal enum value is still an illegal
    destination, because a transition "is accepted only when that destination
    both equals the daypart implied by the logical clock's current UTC
    time-of-day and differs from the store's present `current_daypart`". The
    clock will not rewind, since "The clock is monotonic non-decreasing: a
    requested instant that is at or before the current clock value is rejected
    with `ERR_CLOCK_REGRESSION` (HTTP 422)." And a redemption cannot overdraw,
    because "A negative adjustment that would drive `points_balance` below zero
    is rejected with `ERR_POINTS_BALANCE_NEGATIVE` (HTTP 422)".

    Design: Corner/errors/platform_rejections_cover_the_clock_points_and_plan_error_ids
    """
    X.set_clock(api, CLOCK_LUNCH)
    store = X.create_store(api)
    X.transition_daypart(api, store["id"], "LUNCH")
    plan = X.create_staffing_plan(api, store["id"], daypart="LUNCH")
    X.publish_staffing_plan(api, plan["id"])
    locked = H.get_success_data(
        api.lock_staffing_plan(plan["id"], {}, H.STORE_MANAGER_HEADERS), 200
    )
    assert locked["status"] == "LOCKED"
    member = X.create_loyalty_account(api, member_code="M-1", email="m1@example.com")
    assert member["points_balance"] == 0

    current_version = X.read_store(api, store["id"])["version"]
    H.validate_error(
        api.create_staffing_plan(
            store["id"],
            F.staffing_plan_payload(
                current_version, daypart="LUNCH", forecast_txn_count=500, mto_share_bp=6000
            ),
            H.STORE_MANAGER_HEADERS,
        ),
        E.ERR_PLAN_LOCKED.value,
        409,
    )
    H.validate_error(
        api.create_daypart_transition(
            store["id"], F.daypart_transition_payload("DINNER"), H.STORE_MANAGER_HEADERS
        ),
        E.ERR_DAYPART_NOT_DUE.value,
        409,
    )
    H.validate_error(
        api.set_clock(F.clock_payload("2026-08-01T10:59:59Z"), H.CHAIN_ADMIN_HEADERS),
        E.ERR_CLOCK_REGRESSION.value,
        422,
    )
    H.validate_error(
        api.create_points_adjustment(
            member["id"],
            F.points_adjustment_payload(-50, "Manual correction"),
            H.CHAIN_ADMIN_HEADERS,
        ),
        E.ERR_POINTS_BALANCE_NEGATIVE.value,
        422,
    )

    still_locked, locked_meta = H.validate_paginated(
        api.list_staffing_plans(store["id"], H.STORE_MANAGER_HEADERS, {"status": "LOCKED"})
    )
    assert locked_meta["total_count"] == 1
    assert still_locked[0]["id"] == plan["id"]
    assert X.read_store(api, store["id"])["current_daypart"] == "LUNCH"
    account = X.read_loyalty_account(api, member["id"])
    assert account["points_balance"] == 0
    assert account["lifetime_points_earned"] == 0

    _, plan_meta = H.validate_paginated(
        api.list_staffing_plans(
            store["id"], H.STORE_MANAGER_HEADERS, {"service_date": "2026-08-01"}
        )
    )
    assert plan_meta["total_count"] == 1


def test_verification_checks_its_own_state_before_the_units(api):
    """The same call answers NOT_IMPAIRED first and ALREADY_VERIFIED later.

    The two 409s on this endpoint are ordered, and the order is what stops them
    from being swapped: "Third, the action's own `status` must still be `OPEN`; a
    second verification of an already-verified action is rejected with
    `ERR_ACTION_ALREADY_VERIFIED` (HTTP 409). Fourth, the unit reached through
    the reading must currently be in `IMPAIRED` or `LOCKED_OUT`; verifying an
    action whose unit is already `OPERATIONAL` is rejected with
    `ERR_UNIT_NOT_IMPAIRED` (HTTP 409)." A healthy cabinet therefore fails on the
    fourth check, and the same cabinet — healthy again after a successful
    sign-off, since verification "returns the unit to service by driving it
    `IMPAIRED → OPERATIONAL`" and "resets the unit's
    `consecutive_out_of_range_count` to zero" — fails on the third instead.
    Between the two, one cold reading is enough to open the door: "A unit in
    `OPERATIONAL` goes `OPERATIONAL → IMPAIRED`, and its
    `consecutive_out_of_range_count` increases by one, reaching 1."

    Design: Corner/errors/corrective_action_rejections_cover_the_unit_error_ids
    """
    X.set_clock(api, CLOCK_EARLY)
    store = X.create_store(api)
    unit = X.create_bakery_case(api, store["id"])
    in_range = X.log_temperature(api, unit["id"], 160, H.KITCHEN_ASSOCIATE_HEADERS)
    action = X.open_corrective_action(
        api, in_range["id"], H.SHIFT_LEAD_HEADERS, action_taken="Preventive gasket check"
    )

    H.validate_error(
        api.verify_corrective_action(action["id"], {}, H.SHIFT_LEAD_2_HEADERS),
        E.ERR_UNIT_NOT_IMPAIRED.value,
        409,
    )

    X.log_temperature(api, unit["id"], 120, H.KITCHEN_ASSOCIATE_HEADERS)
    verified = H.get_success_data(
        api.verify_corrective_action(action["id"], {}, H.SHIFT_LEAD_2_HEADERS), 200
    )
    assert verified["status"] == "VERIFIED"

    H.validate_error(
        api.verify_corrective_action(action["id"], {}, H.SHIFT_LEAD_2_HEADERS),
        E.ERR_ACTION_ALREADY_VERIFIED.value,
        409,
    )

    restored = X.read_holding_unit(api, unit["id"])
    assert restored["status"] == "OPERATIONAL"
    assert restored["consecutive_out_of_range_count"] == 0

    _, verified_meta = H.validate_paginated(
        api.list_corrective_actions(H.SHIFT_LEAD_HEADERS, {"status": "VERIFIED"})
    )
    _, open_meta = H.validate_paginated(
        api.list_corrective_actions(H.SHIFT_LEAD_HEADERS, {"status": "OPEN"})
    )
    assert verified_meta["total_count"] == 1
    assert open_meta["total_count"] == 0
