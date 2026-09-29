"""Rules that decide whether a request is even admissible.

Some inputs are reserved for the system, some boundaries are inclusive and
must pass, and some requests break two rules at once so only the pipeline
order can say which error comes back. Each refusal is also checked for having
written nothing at all.
"""

import test_helpers as H
from test_helpers import factories as F
from test_helpers import fixtures as X

CLOCK_EARLY = "2026-08-01T06:00:00Z"
CLOCK_LUNCH = "2026-08-01T11:00:00Z"

CATERING_WINDOW = ("2026-08-01T23:00:00Z", "2026-08-01T23:30:00Z")
LEAD_ONE_MINUTE_SHORT = ("2026-08-01T11:14:00Z", "2026-08-01T11:44:00Z")
LEAD_EXACTLY_FIFTEEN = ("2026-08-01T11:15:00Z", "2026-08-01T11:45:00Z")


def _forty_pretzels_holding(api):
    """A pulled pan of 40 pretzels sitting in slot 1, batch version 3."""
    X.set_clock(api, CLOCK_EARLY)
    store = X.create_store(api)
    unit = X.create_bakery_case(api, store["id"])
    pretzel = X.create_pretzel(api)
    batch = X.create_holding_batch(
        api, store["id"], pretzel["id"], unit["id"], bake_start_at=CLOCK_EARLY
    )
    return store, unit, pretzel, batch


def _catering_draft(api, store, hoagie, qty):
    order = X.create_draft_catering_order(api, store["id"], *CATERING_WINDOW)
    line = X.add_order_line(api, order["id"], hoagie["id"], qty)
    return order, line


def test_a_reason_reserved_for_the_system_sweeps_cannot_be_declared_by_hand(api):
    """UNIT_IMPAIRED is in the vocabulary but not in the operator's half of it.

    "the declared `reason` must be either `HOLD_EXPIRED` or `QUALITY_REJECT`,
    otherwise `ERR_RESERVED_DISCARD_REASON` (HTTP 422)", because "The reason
    vocabulary is deliberately partitioned by provenance: `HOLD_EXPIRED` and
    `QUALITY_REJECT` are operator-declared, while `UNIT_IMPAIRED` and
    `DAYPART_TRANSITION` are reserved for system cascades and may never be
    supplied by a caller." A refused write-off must leave every column of the
    ledger alone, since only "A successful write-off subtracts the `qty` from
    `remaining_qty` and adds it to `discarded_qty`, then appends a waste
    record".

    Design: Corner/validations/discard_with_a_system_only_reason_is_rejected
    """
    store, unit, pretzel, batch = _forty_pretzels_holding(api)
    assert batch["version"] == 3

    response = api.discard_production_batch(
        batch["id"],
        F.discard_payload(5, "UNIT_IMPAIRED", batch["version"]),
        H.SHIFT_LEAD_HEADERS,
    )

    H.validate_error(response, H.ApiErrorId.ERR_RESERVED_DISCARD_REASON.value, 422)
    after = X.read_batch(api, batch["id"])
    assert after["status"] == "HOLDING"
    assert after["remaining_qty"] == 40
    assert after["discarded_qty"] == 0
    assert after["version"] == 3

    _, meta = H.validate_paginated(api.list_batch_waste_logs(batch["id"], H.STORE_MANAGER_HEADERS))
    assert meta["total_count"] == 0
    assert X.read_store(api, store["id"])["waste_cost_cents_mtd"] == 0


def test_a_catering_window_exactly_twelve_hours_out_is_enough_lead(api):
    """720 minutes of lead is sufficient, and the fee floor then bites.

    "a `CATERING` order requires at least twelve hours — 720 minutes — of
    lead", an at-least comparison that a window opening exactly twelve hours
    after the clock satisfies. The subtotal clears the gate that "the order's
    `subtotal_gross_cents` must reach at least 5000 cents", and the fee takes
    the floor: "For a `CATERING` order it is whichever is larger: a floor of
    500 cents, or the discounted food figure multiplied by 800 basis points and
    divided by ten thousand" - eight percent of 5394 is 432, so 500 stands and
    "step six computes `total_cents` as the gross subtotal minus the discount
    plus the service fee".

    Design: Corner/validations/catering_order_placed_exactly_at_the_720_minute_lead_succeeds
    """
    store = X.setup_store_open_for_lunch(api, CLOCK_LUNCH)
    hoagie = X.create_hoagie(api)
    order, line = _catering_draft(api, store, hoagie, 6)
    assert line["line_gross_cents"] == 5394

    placed = X.place_order(api, order["id"])

    assert placed["production_status"] == "PLACED"
    assert placed["service_fee_cents"] == 500
    assert placed["total_cents"] == 5894
    assert placed["daypart_at_placement"] == "LUNCH"
    assert placed["subtotal_gross_cents"] == 5394
    assert placed["promo_discount_cents"] == 0
    assert placed["applied_promotion_id"] is None
    assert placed["settlement_status"] == "UNPAID"


def test_the_missing_plan_is_reported_before_the_catering_minimum(api):
    """An 899-cent catering order under a draft plan reports the plan.

    Both rules are broken at once, and "Onward, the domain rules in exactly
    this order — this is the tie-breaking sequence whenever a single request
    would fail more than one of them: `ERR_ORDER_EMPTY`, then
    `ERR_DAYPART_PLAN_NOT_PUBLISHED`" puts the plan gate near the front while
    `ERR_ORDER_MINIMUM_NOT_MET` is the very last entry of that same sequence.
    So the answer is the 409 from "absent such a plan the commit is refused
    with `ERR_DAYPART_PLAN_NOT_PUBLISHED` (HTTP 409)", and the order keeps the
    money columns of an untouched draft, where `placed_at` is among the fields
    "null until the workflow stages that populate them".

    Design: Corner/validations/unpublished_plan_error_wins_over_the_catering_minimum_error
    """
    X.set_clock(api, CLOCK_LUNCH)
    store = X.create_store(api)
    X.transition_daypart(api, store["id"], "LUNCH")
    plan = X.create_staffing_plan(api, store["id"], daypart="LUNCH")
    assert plan["status"] == "DRAFT"
    hoagie = X.create_hoagie(api)
    order, _ = _catering_draft(api, store, hoagie, 1)

    response = api.place_order(order["id"], {}, H.STORE_TERMINAL_HEADERS)

    H.validate_error(response, H.ApiErrorId.ERR_DAYPART_PLAN_NOT_PUBLISHED.value, 409)
    assert (
        response.json()["data"]["error_id"] != H.ApiErrorId.ERR_ORDER_MINIMUM_NOT_MET.value
    )
    after = X.read_order(api, order["id"])
    assert after["production_status"] == "DRAFT"
    assert after["placed_at"] is None
    assert after["total_cents"] == 0


def test_borrowing_a_modifier_from_another_item_outranks_its_quantity_limit(api):
    """The foreign option is reported before anyone looks at its qty of 9.

    The espresso shot belongs to the coffee, so "Every referenced modifier
    option must belong to the line's own `menu_item_id`; borrowing an option
    from a different item is rejected with `ERR_MODIFIER_NOT_FOR_ITEM` (HTTP
    422)", and nine units of a max-2 option would also trip "each modifier
    entry's `qty` must be at least 1 and must not exceed that option's
    `max_qty`, otherwise `ERR_MODIFIER_LIMIT_EXCEEDED` (HTTP 422)". The
    domain-rule sequence settles it: "then `ERR_MODIFIER_NOT_FOR_ITEM`, then
    `ERR_MENU_ITEM_NOT_IN_DAYPART`, then `ERR_ITEM_NOT_CATERING_ELIGIBLE`, then
    `ERR_ITEM_NOT_PAR_BAKED`, then `ERR_MODIFIER_LIMIT_EXCEEDED`".

    Design: Corner/validations/modifier_ownership_error_wins_over_the_modifier_limit_error
    """
    store = X.create_store(api)
    hoagie = X.create_hoagie(api)
    X.create_modifier_option(
        api, hoagie["id"], code="EXTRA-PROV", modifier_class="CHEESE",
        price_delta_cents=60, is_premium=True, max_qty=1,
    )
    coffee = X.create_coffee(api)
    shot = X.create_modifier_option(
        api, coffee["id"], code="ESPRESSO-SHOT", modifier_class="PREP",
        price_delta_cents=90, is_premium=True, max_qty=2,
    )
    order = X.create_draft_order(api, store["id"])

    response = api.create_order_line(
        order["id"],
        F.order_line_payload(hoagie["id"], 1, [F.modifier_selection(shot["id"], 9)]),
        H.STORE_TERMINAL_HEADERS,
    )

    H.validate_error(response, H.ApiErrorId.ERR_MODIFIER_NOT_FOR_ITEM.value, 422)
    assert (
        response.json()["data"]["error_id"] != H.ApiErrorId.ERR_MODIFIER_LIMIT_EXCEEDED.value
    )
    assert X.read_order(api, order["id"])["subtotal_gross_cents"] == 0
    _, meta = H.validate_paginated(
        api.list_order_lines(H.STORE_MANAGER_HEADERS, {"order_id": order["id"]})
    )
    assert meta["total_count"] == 0


def test_the_preorder_lead_boundary_refuses_fourteen_minutes_and_accepts_fifteen(api):
    """One minute either side of the fifteen-minute lead, at one clock.

    "A `MOBILE_PREORDER` order requires that its `pickup_window_start` be at
    least 15 minutes after the current logical clock", an at-least comparison,
    so 11:14 fails and 11:15 passes. "Either shortfall reports
    `ERR_PREORDER_LEAD_TIME_TOO_SHORT` (HTTP 422)" and leaves the draft alone,
    with `placed_at` still among the fields "null until the workflow stages that
    populate them"; the accepted commit sets "`placed_at` ... to the current
    logical-clock instant and `daypart_at_placement` snapshots the store's
    `current_daypart`", and carries no fee, since "The order's
    `service_fee_cents` is 0 for a `TOUCHSCREEN` or `MOBILE_PREORDER` order".

    Design: Corner/validations/preorder_one_minute_inside_the_fifteen_minute_lead_is_rejected
    """
    store = X.setup_store_open_for_lunch(api, CLOCK_LUNCH)
    coffee = X.create_coffee(api)

    def preorder(window):
        order = X.create_draft_preorder(api, store["id"], window[0], window[1])
        X.add_order_line(api, order["id"], coffee["id"], 1)
        return order

    too_early = preorder(LEAD_ONE_MINUTE_SHORT)
    on_the_boundary = preorder(LEAD_EXACTLY_FIFTEEN)

    refused = api.place_order(too_early["id"], {}, H.STORE_TERMINAL_HEADERS)

    H.validate_error(refused, H.ApiErrorId.ERR_PREORDER_LEAD_TIME_TOO_SHORT.value, 422)
    still_draft = X.read_order(api, too_early["id"])
    assert still_draft["production_status"] == "DRAFT"
    assert still_draft["placed_at"] is None

    placed = X.place_order(api, on_the_boundary["id"])

    assert placed["production_status"] == "PLACED"
    assert placed["total_cents"] == 249
    assert placed["service_fee_cents"] == 0
    assert placed["daypart_at_placement"] == "LUNCH"


def test_the_daypart_gate_reads_the_store_not_the_clock(api):
    """A LUNCH-only coffee is refused at 11:00 while the store says BREAKFAST.

    "The menu item's `valid_dayparts` must include the store's
    `current_daypart`, checked when the line is added and re-checked when the
    order is committed; a violation reports `ERR_MENU_ITEM_NOT_IN_DAYPART`
    (HTTP 422)." A freshly registered store opens in BREAKFAST regardless of
    the clock, and the flip is an explicit act: "the store's `current_daypart`
    becomes the requested `to_daypart`". Nothing about the order or the item
    changes between the two attempts, and the accepted line copies its routing
    where "the line's `station` is copied from the menu item's `station`".

    Design: Corner/validations/line_creation_is_gated_on_the_stores_current_daypart
    """
    X.set_clock(api, CLOCK_LUNCH)
    store = X.create_store(api)
    assert store["current_daypart"] == "BREAKFAST"
    coffee = X.create_coffee(api, valid_dayparts=["LUNCH"])
    order = X.create_draft_order(api, store["id"])

    refused = api.create_order_line(
        order["id"], F.order_line_payload(coffee["id"], 1), H.STORE_TERMINAL_HEADERS
    )

    H.validate_error(refused, H.ApiErrorId.ERR_MENU_ITEM_NOT_IN_DAYPART.value, 422)

    flipped = X.transition_daypart(api, store["id"], "LUNCH")
    assert flipped["current_daypart"] == "LUNCH"

    line = X.add_order_line(api, order["id"], coffee["id"], 1)

    assert line["line_gross_cents"] == 249
    assert line["station"] == "BEVERAGE"
    assert X.read_order(api, order["id"])["subtotal_gross_cents"] == 249
    _, meta = H.validate_paginated(
        api.list_order_lines(H.STORE_MANAGER_HEADERS, {"order_id": order["id"]})
    )
    assert meta["total_count"] == 1


def test_a_fuel_combo_is_dropped_at_a_store_that_sells_no_fuel(api):
    """Forty gallons on file cannot rescue a combo at an inline store.

    "A rule whose `kind` is `FUEL_FOOD_COMBO` carries three extra
    requirements: the store must be flagged `is_fuel_site`, the order must have
    a non-null `loyalty_account_id`, and that member's thirty-day gallon total
    from §3.2 must be at least the rule's `requires_fuel_gallons`." Two of the
    three hold and the site flag does not, so the combo never enters the pool
    and the smaller daypart bundle wins by default - "A `DAYPART_BUNDLE` rule
    has no fuel requirement." Accrual then reads the discounted total, since
    the provisional basis "is the order's `total_cents`".

    Design: Corner/validations/fuel_combo_is_ineligible_at_a_non_fuel_site
    """
    store = X.setup_store_open_for_lunch(
        api, CLOCK_LUNCH, store_code="WAWA-0199", name="Wawa Inline Store", is_fuel_site=False
    )
    assert store["is_fuel_site"] is False
    member = X.create_loyalty_account(api, member_code="M-1", email="m1@example.com")
    X.record_fuel(api, member["id"], gallons=40.0, occurred_at=CLOCK_LUNCH)
    combo = H.get_success_data(
        api.create_promotion_rule(
            F.fuel_combo_promotion_payload(
                code="FUEL900", discount_cents=900, max_discount_cents=900,
                min_food_subtotal_cents=0, requires_fuel_gallons=10, stacking_rank=1,
            ),
            H.CHAIN_ADMIN_HEADERS,
        ),
        201,
    )
    bundle = H.get_success_data(
        api.create_promotion_rule(
            F.cents_off_promotion_payload(
                code="BUNDLE100", discount_cents=100, max_discount_cents=100, stacking_rank=9
            ),
            H.CHAIN_ADMIN_HEADERS,
        ),
        201,
    )
    hoagie = X.create_hoagie(api)
    order = X.create_draft_order(api, store["id"], loyalty_account_id=member["id"])
    X.add_order_line(api, order["id"], hoagie["id"], 1)

    placed = X.place_order(api, order["id"])

    assert placed["applied_promotion_id"] == bundle["id"]
    assert placed["applied_promotion_id"] != combo["id"]
    assert placed["promo_discount_cents"] == 100
    assert placed["total_cents"] == 799
    assert placed["points_provisional"] == 7


def test_an_unresolvable_menu_item_is_a_not_found_before_any_daypart_check(api):
    """The item cannot be judged against the daypart until it resolves.

    Body foreign keys are step 5 of the pipeline, "Foreign keys carried in the
    request body, resolved in the order the fields are declared in the
    endpoint's input list. This step applies to order creation, line creation,
    production-batch creation and corrective-action creation, and may yield
    `ERR_STORE_NOT_FOUND`, `ERR_MENU_ITEM_NOT_FOUND`", while the daypart rule
    is a domain rule far below it. "Validation is a fixed pipeline and the
    **first** failure wins; later checks are never reached and never reported."

    Design: Corner/validations/unknown_menu_item_on_line_create_beats_the_daypart_check
    """
    store = X.create_store(api)
    order = X.create_draft_order(api, store["id"])

    response = api.create_order_line(
        order["id"], F.order_line_payload(H.NON_EXISTENT_UUID, 1), H.STORE_TERMINAL_HEADERS
    )

    H.validate_error(response, H.ApiErrorId.ERR_MENU_ITEM_NOT_FOUND.value, 404)
    assert (
        response.json()["data"]["error_id"] != H.ApiErrorId.ERR_MENU_ITEM_NOT_IN_DAYPART.value
    )
    assert X.read_order(api, order["id"])["subtotal_gross_cents"] == 0
    _, meta = H.validate_paginated(
        api.list_order_lines(H.STORE_MANAGER_HEADERS, {"order_id": order["id"]})
    )
    assert meta["total_count"] == 0
