"""Every cent and every point, computed the one way the contract allows.

Line pricing multiplies the premium surcharge per unit; per-line percentage
discounts round half up before they are summed and are clawed back off the
last line when the cap bites; promotion selection ranks on discount size and
only then on rank; ticket clocks are read off the station queue. Each test
pins one arithmetic decision at the input where a wrong reading diverges.
"""

import test_helpers as H
from test_helpers import factories as F
from test_helpers import fixtures as X

CLOCK_LUNCH = "2026-08-01T11:00:00Z"
CLOCK_EARLY = "2026-08-01T06:00:00Z"

WINDOW_OPENS_AT = "2026-07-02T11:00:00Z"
ONE_SECOND_BEFORE_THE_WINDOW = "2026-07-02T10:59:59Z"


def _premium_hoagie_with_two_options(api):
    """A hoagie allowing one premium free, plus 60c cheese and 150c bacon."""
    hoagie = X.create_hoagie(api)
    provolone = X.create_modifier_option(
        api, hoagie["id"], code="EXTRA-PROV", modifier_class="CHEESE",
        price_delta_cents=60, is_premium=True, max_qty=1,
    )
    bacon = X.create_modifier_option(
        api, hoagie["id"], code="EXTRA-BACON", modifier_class="PROTEIN",
        price_delta_cents=150, is_premium=True, max_qty=2,
    )
    return hoagie, provolone, bacon


def _three_premium_units(provolone, bacon):
    return [F.modifier_selection(provolone["id"], 1), F.modifier_selection(bacon["id"], 2)]


def _promotion(api, payload):
    return H.get_success_data(api.create_promotion_rule(payload, H.CHAIN_ADMIN_HEADERS), 201)


def test_the_premium_surcharge_is_charged_per_unit_and_scaled_by_line_qty(api):
    """Three premium units on a two-unit line price to 2818 cents.

    "the line's `unit_price_cents` is the menu item's `base_price_cents` plus,
    for every modifier entry on the line, that option's `price_delta_cents`
    multiplied by the entry's `qty`" gives 899 + 60 + 300 = 1259, and "the
    line's `premium_surcharge_cents` is 75 cents multiplied by the amount,
    never less than zero, by which the premium modifier unit count exceeds the
    menu item's `included_premium_count`" charges 2 of the 3 units, 150 cents.
    Then "the line's `line_gross_cents` is the sum of `unit_price_cents` and
    `premium_surcharge_cents`, that whole sum then multiplied by the line's
    `qty`" - the surcharge rides inside the multiplication, not beside it.

    Design: Corner/calculations/line_gross_pricing_with_three_premium_units_computes_2818
    """
    store = X.create_store(api)
    hoagie, provolone, bacon = _premium_hoagie_with_two_options(api)
    order = X.create_draft_order(api, store["id"])

    line = H.get_success_data(
        api.create_order_line(
            order["id"],
            F.order_line_payload(hoagie["id"], 2, _three_premium_units(provolone, bacon)),
            H.STORE_TERMINAL_HEADERS,
        ),
        201,
    )

    assert line["unit_price_cents"] == 1259
    assert line["premium_surcharge_cents"] == 150
    assert line["line_gross_cents"] == 2818
    assert line["station"] == "SANDWICH"
    assert line["line_discount_cents"] == 0
    assert line["line_net_cents"] == 0
    after = X.read_order(api, order["id"])
    assert after["subtotal_gross_cents"] == 2818
    assert after["promo_discount_cents"] == 0
    assert after["total_cents"] == 0


def test_a_suspended_rule_leaves_the_field_to_the_smaller_active_bundle(api):
    """The 900-cent rule is out of the pool, so 200 cents is applied.

    "A rule opens in the `ACTIVE` status and only active rules ever enter the
    candidate pool. A `ChainAdmin` may suspend a rule, moving its `status` to
    `SUSPENDED`; from that moment the selector stops considering it". Only the
    surviving candidate is left, and "The candidate pool is every promotion
    rule whose `status` is `ACTIVE` — suspended rules are excluded outright"
    settles which one that is. Totals then follow the pinned order, "step six
    computes `total_cents` as the gross subtotal minus the discount plus the
    service fee", with no fee on a touchscreen sale.

    Design: Corner/calculations/promotion_selection_ignores_a_suspended_rule
    """
    store = X.setup_store_open_for_lunch(api, CLOCK_LUNCH)
    big = _promotion(
        api,
        F.cents_off_promotion_payload(
            code="BIG-BUNDLE", discount_cents=900, max_discount_cents=900, stacking_rank=1
        ),
    )
    small = _promotion(
        api,
        F.cents_off_promotion_payload(
            code="SMALL-BUNDLE", discount_cents=200, max_discount_cents=200, stacking_rank=2
        ),
    )
    suspended = H.get_success_data(api.suspend_promotion_rule(big["id"], {}, H.CHAIN_ADMIN_HEADERS))
    assert suspended["status"] == "SUSPENDED"

    hoagie = X.create_hoagie(api)
    order = X.create_draft_order(api, store["id"])
    X.add_order_line(api, order["id"], hoagie["id"], 1)

    placed = X.place_order(api, order["id"])

    assert placed["applied_promotion_id"] == small["id"]
    assert placed["promo_discount_cents"] == 200
    assert placed["total_cents"] == 699
    assert placed["subtotal_gross_cents"] == 899
    assert placed["service_fee_cents"] == 0

    _, active_meta = H.validate_paginated(
        api.list_promotion_rules(H.CHAIN_ADMIN_HEADERS, {"status": "ACTIVE"})
    )
    _, suspended_meta = H.validate_paginated(
        api.list_promotion_rules(H.CHAIN_ADMIN_HEADERS, {"status": "SUSPENDED"})
    )
    assert active_meta["total_count"] == 1
    assert suspended_meta["total_count"] == 1


def test_modifier_handling_is_charged_per_modifier_unit_on_the_ticket_clock(api):
    """Three modifier units add 45 seconds to a 180-second build.

    "A ticket's `prep_seconds` is the sum, over the order's `MADE_TO_ORDER`
    lines routed to that ticket's station, of the menu item's `prep_seconds`
    multiplied by the line's `qty`, plus 15 seconds of modifier handling
    multiplied by the line's total modifier unit count and again by the line's
    `qty`. A line's modifier unit count is the sum of the `qty` figures across
    its modifier entries." One provolone and two bacon is three units, so 225
    seconds, and on an empty queue "Its `promised_ready_at` is the current
    logical-clock instant advanced by its `lead_seconds` and then by its own
    `prep_seconds`, expressed in whole seconds".

    Design: Corner/calculations/ticket_prep_seconds_adds_fifteen_seconds_per_modifier_unit
    """
    store = X.setup_store_open_for_lunch(api, CLOCK_LUNCH)
    hoagie, provolone, bacon = _premium_hoagie_with_two_options(api)
    order = X.create_draft_order(api, store["id"])
    line = X.add_order_line(
        api, order["id"], hoagie["id"], 1, _three_premium_units(provolone, bacon)
    )
    assert line["line_gross_cents"] == 1409

    placed = X.place_order(api, order["id"])

    assert placed["expected_ready_at"] == "2026-08-01T11:03:45Z"
    ticket = X.find_ticket(api, placed["id"], "SANDWICH")
    assert ticket["prep_seconds"] == 225
    assert ticket["lead_seconds"] == 0
    assert ticket["sequence_position"] == 1
    assert ticket["promised_ready_at"] == "2026-08-01T11:03:45Z"
    assert ticket["status"] == "QUEUED"

    _, meta = H.validate_paginated(
        api.list_kitchen_tickets(H.KITCHEN_ASSOCIATE_HEADERS, {"order_id": placed["id"]})
    )
    assert meta["total_count"] == 1


def test_a_line_discount_of_exactly_half_a_cent_rounds_upwards(api):
    """249 cents at 5000 basis points discounts 125, not 124.

    "each line's `line_discount_cents` is that line's `line_gross_cents`
    multiplied by the rule's `discount_bp` and divided by ten thousand,
    **rounded half up per line**, and the raw discount is the sum of those
    already-rounded per-line figures." Half of 249 is exactly 124.5, the one
    input where the rounding mode is visible. The cap does not interfere,
    because "the order's `promo_discount_cents` is the smaller of the raw
    discount and the rule's `max_discount_cents`" and 900 is far above it, and
    "Each line's `line_net_cents` is finally its `line_gross_cents` minus its
    `line_discount_cents`" leaves 124 on the line.

    Design: Corner/calculations/pct_per_line_discount_rounds_half_up_at_exactly_half_a_cent
    """
    store = X.setup_store_open_for_lunch(api, CLOCK_LUNCH)
    rule = _promotion(
        api,
        F.promotion_rule_payload(
            code="PCT-HALF", discount_bp=5000, max_discount_cents=900,
            stacking_rank=1, target_station="ALL",
        ),
    )
    coffee = X.create_coffee(api)
    order = X.create_draft_order(api, store["id"])
    line = X.add_order_line(api, order["id"], coffee["id"], 1)

    placed = X.place_order(api, order["id"])

    assert placed["applied_promotion_id"] == rule["id"]
    assert placed["promo_discount_cents"] == 125
    assert placed["total_cents"] == 124
    assert placed["subtotal_gross_cents"] == 249
    priced = X.read_order_line(api, line["id"])
    assert priced["line_gross_cents"] == 249
    assert priced["line_discount_cents"] == 125
    assert priced["line_net_cents"] == 124


def test_the_surcharge_engages_on_the_first_unit_past_the_allowance(api):
    """One and two premium units cost nothing extra; the third costs 75.

    With an allowance of two, "the line's `premium_surcharge_cents` is 75 cents
    multiplied by the amount, never less than zero, by which the premium
    modifier unit count exceeds the menu item's `included_premium_count`" is
    zero at one unit and at two, and 75 at three. The unit price still climbs
    with every unit, since it is "the menu item's `base_price_cents` plus, for
    every modifier entry on the line, that option's `price_delta_cents`
    multiplied by the entry's `qty`", so only the surcharge column isolates the
    threshold. Each add "recomputes the order's `subtotal_gross_cents` as the
    sum of the `line_gross_cents` of all its remaining lines".

    Design: Corner/calculations/premium_surcharge_engages_only_one_unit_past_the_included_count
    """
    store = X.create_store(api)
    hoagie = X.create_menu_item(api, included_premium_count=2, is_catering_eligible=True)
    bacon = X.create_modifier_option(
        api, hoagie["id"], code="EXTRA-BACON", modifier_class="PROTEIN",
        price_delta_cents=150, is_premium=True, max_qty=3,
    )
    order = X.create_draft_order(api, store["id"])

    lines = [
        X.add_order_line(
            api, order["id"], hoagie["id"], 1, [F.modifier_selection(bacon["id"], units)]
        )
        for units in (1, 2, 3)
    ]

    assert [line["premium_surcharge_cents"] for line in lines] == [0, 0, 75]
    assert [line["line_gross_cents"] for line in lines] == [1049, 1199, 1424]
    assert [line["unit_price_cents"] for line in lines] == [1049, 1199, 1349]
    assert lines[2]["line_net_cents"] == 0
    assert X.read_order(api, order["id"])["subtotal_gross_cents"] == 3672

    _, meta = H.validate_paginated(
        api.list_order_lines(H.STORE_MANAGER_HEADERS, {"order_id": order["id"]})
    )
    assert meta["total_count"] == 3


def test_both_closed_bounds_of_the_fuel_window_count_toward_the_combo(api):
    """Exactly ten gallons qualify, and a sale one second early does not.

    "The window opens thirty days before the current logical-clock instant, and
    a fuel sale participates when its `occurred_at` is at or after that opening
    instant and at or before the clock itself — both bounds inclusive." Six
    gallons at the opening instant plus four at the clock is exactly ten, and
    "The resulting gallon total is summed at three decimal places and compared
    against a promotion's requirement with an at-least comparison, so a member
    with exactly the required gallonage qualifies." The twenty-gallon sale one
    second before the opening instant stays outside, so the twenty-five-gallon
    rule never becomes a candidate, its requirement being that "that member's
    thirty-day gallon total from §3.2 must be at least the rule's
    `requires_fuel_gallons`".

    Design: Corner/calculations/fuel_lookback_window_includes_both_of_its_closed_bounds
    """
    store = X.setup_store_open_for_lunch(api, CLOCK_LUNCH)
    member = X.create_loyalty_account(api, member_code="M-1", email="m1@example.com")
    X.record_fuel(api, member["id"], gallons=20.0, occurred_at=ONE_SECOND_BEFORE_THE_WINDOW)
    X.record_fuel(api, member["id"], gallons=6.0, occurred_at=WINDOW_OPENS_AT)
    X.record_fuel(api, member["id"], gallons=4.0, occurred_at=CLOCK_LUNCH)
    ten_gallon_rule = _promotion(
        api,
        F.fuel_combo_promotion_payload(
            code="FUEL10", discount_cents=300, max_discount_cents=300,
            min_food_subtotal_cents=0, requires_fuel_gallons=10, stacking_rank=1,
        ),
    )
    twenty_five_gallon_rule = _promotion(
        api,
        F.fuel_combo_promotion_payload(
            code="FUEL25", discount_cents=800, max_discount_cents=800,
            min_food_subtotal_cents=0, requires_fuel_gallons=25, stacking_rank=2,
        ),
    )
    hoagie = X.create_hoagie(api)
    order = X.create_draft_order(api, store["id"], loyalty_account_id=member["id"])
    X.add_order_line(api, order["id"], hoagie["id"], 1)

    placed = X.place_order(api, order["id"])

    assert placed["applied_promotion_id"] == ten_gallon_rule["id"]
    assert placed["applied_promotion_id"] != twenty_five_gallon_rule["id"]
    assert placed["promo_discount_cents"] == 300
    assert placed["total_cents"] == 599
    assert placed["points_provisional"] == 5
    assert placed["subtotal_gross_cents"] == 899

    _, meta = H.validate_paginated(
        api.list_fuel_transactions(member["id"], H.STORE_TERMINAL_HEADERS)
    )
    assert meta["total_count"] == 3


def test_the_second_sandwich_ticket_queues_behind_the_first_at_the_same_instant(api):
    """Two commits at one clock instant give sequences 1 and 2, not 1 and 1.

    "The queue a new ticket joins consists of the tickets of the same `store_id`
    and the same `station` whose `status` is `QUEUED` or `IN_PROGRESS`", and
    "The new ticket's `sequence_position` is one more than the number of
    tickets already in that queue, counted **before** the new ticket is
    inserted.
    Its `lead_seconds` is the sum of the `prep_seconds` of exactly those tickets
    ahead of it." The first ticket is still queued when the second commit runs,
    so the second inherits 180 seconds of lead and promises three minutes
    later, and "The order's `expected_ready_at` is the latest
    `promised_ready_at` among the tickets this commit created".

    Design: Corner/calculations/second_sandwich_ticket_takes_sequence_two_and_inherits_the_lead
    """
    store = X.setup_store_open_for_lunch(api, CLOCK_LUNCH)
    hoagie = X.create_hoagie(api)

    def draft_with_one_hoagie():
        order = X.create_draft_order(api, store["id"])
        X.add_order_line(api, order["id"], hoagie["id"], 1)
        return order

    first = draft_with_one_hoagie()
    second = draft_with_one_hoagie()

    placed_first = X.place_order(api, first["id"])
    placed_second = X.place_order(api, second["id"])

    ticket_first = X.find_ticket(api, placed_first["id"], "SANDWICH")
    assert ticket_first["sequence_position"] == 1
    assert ticket_first["lead_seconds"] == 0
    assert ticket_first["prep_seconds"] == 180
    assert placed_first["expected_ready_at"] == "2026-08-01T11:03:00Z"

    ticket_second = X.find_ticket(api, placed_second["id"], "SANDWICH")
    assert ticket_second["sequence_position"] == 2
    assert ticket_second["lead_seconds"] == 180
    assert ticket_second["promised_ready_at"] == "2026-08-01T11:06:00Z"
    assert placed_second["expected_ready_at"] == "2026-08-01T11:06:00Z"

    _, meta = H.validate_paginated(
        api.get_store_kitchen_queue(
            store["id"], H.KITCHEN_ASSOCIATE_HEADERS, {"station": "SANDWICH"}
        )
    )
    assert meta["total_count"] == 2


def test_the_discount_cap_is_shaved_off_the_last_eligible_line(api):
    """450 plus 125 is clipped to 500 by taking 75 off the coffee alone.

    Raw per-line figures are "**rounded half up per line**, and the raw discount is
    the sum of those already-rounded per-line figures", giving 450 and 125, and
    the cap clips the order figure because "the order's `promo_discount_cents`
    is the smaller of the raw discount and the rule's `max_discount_cents`".
    The line columns must then be reconciled the pinned way: "cents are removed
    from the **last** eligible line in descending `created_at` order until the sum
    agrees. The identity that the per-line discounts sum to the order's
    discount always holds." Pro-rata scaling would move both lines instead.

    Design: Corner/calculations/pct_per_line_cap_redistribution_shaves_the_last_eligible_line
    """
    store = X.setup_store_open_for_lunch(api, CLOCK_LUNCH)
    rule = _promotion(
        api,
        F.promotion_rule_payload(
            code="PCT-CAP", discount_bp=5000, max_discount_cents=500,
            stacking_rank=1, target_station="ALL",
        ),
    )
    hoagie = X.create_hoagie(api)
    coffee = X.create_coffee(api)
    order = X.create_draft_order(api, store["id"])
    hoagie_line = X.add_order_line(api, order["id"], hoagie["id"], 1)
    coffee_line = X.add_order_line(api, order["id"], coffee["id"], 1)

    placed = X.place_order(api, order["id"])

    assert placed["applied_promotion_id"] == rule["id"]
    assert placed["promo_discount_cents"] == 500
    assert placed["total_cents"] == 648
    assert placed["subtotal_gross_cents"] == 1148

    priced_hoagie = X.read_order_line(api, hoagie_line["id"])
    priced_coffee = X.read_order_line(api, coffee_line["id"])
    assert priced_hoagie["line_discount_cents"] == 450
    assert priced_hoagie["line_net_cents"] == 449
    assert priced_coffee["line_discount_cents"] == 50
    assert priced_coffee["line_net_cents"] == 199
    assert (
        priced_hoagie["line_discount_cents"] + priced_coffee["line_discount_cents"]
        == placed["promo_discount_cents"]
    )


def test_discount_size_beats_a_better_stacking_rank(api):
    """The rank-5 rule taking 900 cents wins over the rank-1 rule taking 200.

    "Candidates are then ranked by the discount each would actually produce,
    cap included: the rule producing the **largest** discount wins; where two
    produce the same discount the one with the **lower** `stacking_rank` wins; and
    where those also tie the one with the earlier `created_at` wins." Rank is a
    tie-break and nothing more, so the bigger discount takes the order even
    though its rank is worse. The losing rule leaves no trace, because
    "Promotion selection picks exactly one rule; promotions never stack", and
    orders are "listed with filters on `store_id`, `loyalty_account_id`,
    `applied_promotion_id`, `production_status`, `settlement_status` and
    `channel`".

    Design: Corner/calculations/promotion_selection_prefers_the_bigger_discount_over_the_lower_rank
    """
    store = X.setup_store_open_for_lunch(api, CLOCK_LUNCH)
    small = _promotion(
        api,
        F.cents_off_promotion_payload(
            code="BUNDLE-SMALL", discount_cents=200, max_discount_cents=200, stacking_rank=1
        ),
    )
    big = _promotion(
        api,
        F.cents_off_promotion_payload(
            code="BUNDLE-BIG", discount_cents=900, max_discount_cents=900, stacking_rank=5
        ),
    )
    hoagie = X.create_hoagie(api)
    order = X.create_draft_order(api, store["id"])
    X.add_order_line(api, order["id"], hoagie["id"], 2)

    placed = X.place_order(api, order["id"])

    assert placed["applied_promotion_id"] == big["id"]
    assert placed["applied_promotion_id"] != small["id"]
    assert placed["promo_discount_cents"] == 900
    assert placed["total_cents"] == 898
    assert placed["subtotal_gross_cents"] == 1798

    _, big_meta = H.validate_paginated(
        api.list_orders(H.STORE_MANAGER_HEADERS, {"applied_promotion_id": big["id"]})
    )
    _, small_meta = H.validate_paginated(
        api.list_orders(H.STORE_MANAGER_HEADERS, {"applied_promotion_id": small["id"]})
    )
    assert big_meta["total_count"] == 1
    assert small_meta["total_count"] == 0


def test_a_freshly_probed_store_with_no_waste_reads_ready_on_every_figure(api):
    """The all-clear branch of the readiness ladder, all seven figures.

    The single unit was probed at the clock, so it counts toward
    "`temp_log_compliance_pct` ... the share of the store's holding units that
    have at least one probe reading whose `recorded_at` falls at or after the
    instant four hours — 240 minutes — before the current logical clock",
    giving 100. With nothing impaired, nothing locked out, no open action and
    no waste, the verdict falls through to the last rung: "it is `NOT_READY`
    when at least one unit is locked out or the compliance percentage is below
    75; otherwise it is `AT_RISK` when at least one corrective action is open,
    or at least one unit is impaired, or the compliance percentage is below 90;
    otherwise it is `READY`". Both waste columns read zero, since
    "The `food_cost_waste_cents_mtd` figure is the store's
    `waste_cost_cents_mtd` plus its `rework_waste_cents_mtd`".

    Design: Corner/calculations/readiness_reports_ready_for_a_freshly_logged_compliant_store
    """
    X.set_clock(api, CLOCK_EARLY)
    store = X.create_store(api)
    unit = X.create_bakery_case(api, store["id"])
    reading = X.log_temperature(api, unit["id"], 160, H.KITCHEN_ASSOCIATE_HEADERS)
    assert reading["in_range"] is True

    readiness = H.get_success_data(
        api.get_store_readiness(store["id"], H.FOOD_SAFETY_LEAD_HEADERS)
    )

    assert readiness["temp_log_compliance_pct"] == 100
    assert readiness["units_impaired_count"] == 0
    assert readiness["units_locked_out_count"] == 0
    assert readiness["open_corrective_actions_count"] == 0
    assert readiness["food_cost_waste_cents_mtd"] == 0
    assert readiness["retail_waste_exposure_cents"] == 0
    assert readiness["readiness_status"] == "READY"

    probed = X.read_holding_unit(api, unit["id"])
    assert probed["status"] == "OPERATIONAL"
    assert probed["consecutive_out_of_range_count"] == 0
    assert probed["last_temp_log_at"].startswith("2026-08-01T06:00:00")
