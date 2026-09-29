"""Exact-boundary behaviour of the cap, the radius limit and the lunch window."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_employee_with_period,
    api_client,
    create_restaurant,
    draft_order,
    order_line,
    place_order,
    place_order_raw,
    read_order,
    read_period,
    setup_program_base,
    setup_scenario,
    validate_error,
    validate_paginated,
)

_BLOCK_SCENARIO = {
    "group_overrides": {"name": "Interns", "headcount_planned": 1},
    "rule_overrides": {
        "per_meal_cap_cents": 2500,
        "daily_meal_limit": 2,
        "monthly_allocation_cents": 10_000,
        "overage_policy": "BLOCK",
        "tip_coverage_policy": "EMPLOYEE_PAYS_TIP",
    },
}


def test_covered_base_exactly_at_the_per_meal_cap_passes_a_block_policy():
    """A 1,601-cent line prices to a covered base of exactly 2,500 and is admitted.

    PRD §3.5: "Note that landing exactly at the cap is not an overage: when
    `covered_base_cents` equals `per_meal_cap_cents` the employee card amount is 0
    apart from any uncovered tip, and a `BLOCK` group still succeeds."

    Design: Difficulty/boundary_precision_check/covered_base_exactly_at_per_meal_cap_2500_passes_block_policy_2501_fails
    """
    ns = setup_scenario(**_BLOCK_SCENARIO)
    order = draft_order(
        ns.employee,
        ns.period,
        ns.restaurant,
        ns.location,
        lines=[order_line("Set Lunch", 1601, 1)],
    )
    order = place_order(order, ns.employee)

    assert order["subtotal_cents"] == 1601
    assert order["tax_cents"] == 140
    assert order["delivery_fee_cents"] == 599
    assert order["service_fee_cents"] == 160
    assert order["covered_base_cents"] == 2500, (
        f"1,601 + 140 + 599 + 160 is exactly the 2,500 cap, got {order['covered_base_cents']}"
    )
    assert order["employer_covered_cents"] == 2500
    assert order["employee_card_cents"] == 0, "landing on the cap is not an overage"
    assert order["fulfillment_status"] == "PLACED"

    period = read_period(ns.period["id"])
    assert period["reserved_cents"] == 2500
    assert period["available_cents"] == 7500


def test_covered_base_one_cent_past_the_cap_is_refused_under_a_block_policy():
    """A 1,602-cent line prices to 2,501 and leaves one cent on the card.

    PRD §3.5: "If `employee_card_cents` is positive and the pinned
    `overage_policy` is `BLOCK`, the placement is refused with
    `ERR_OVERAGE_NOT_PERMITTED`."

    Design: Difficulty/boundary_precision_check/covered_base_exactly_at_per_meal_cap_2500_passes_block_policy_2501_fails
    """
    ns = setup_scenario(**_BLOCK_SCENARIO)
    first = draft_order(
        ns.employee,
        ns.period,
        ns.restaurant,
        ns.location,
        lines=[order_line("Set Lunch", 1601, 1)],
    )
    place_order(first, ns.employee)

    second = draft_order(
        ns.employee,
        ns.period,
        ns.restaurant,
        ns.location,
        lines=[order_line("Set Lunch Plus", 1602, 1)],
    )
    response = place_order_raw(second, ns.employee)
    validate_error(response, ApiErrorId.ERR_OVERAGE_NOT_PERMITTED)

    assert read_order(second["id"])["fulfillment_status"] == "DRAFT"
    assert read_period(ns.period["id"])["reserved_cents"] == 2500, (
        "the refused placement reserves nothing"
    )


def test_eligible_restaurant_search_admits_exactly_eight_km_and_drops_nine():
    """A rounded distance equal to the 8.0 km ceiling is in range; 9.000 is not.

    PRD §3.4: "Survivors are ranked by that rounded distance ascending and, where
    two restaurants tie on distance, by `name` ascending; the identifier is never
    a sort key."

    Design: Difficulty/boundary_precision_check/delivery_radius_exactly_8_000_km_eligible_while_9_000_km_excluded
    """
    ns = setup_program_base(
        program_overrides={"eligible_cuisines": ["THAI", "SALAD", "PIZZA"]}
    )
    create_restaurant(
        name="Salad Edge",
        cuisine="SALAD",
        grid_x_km=8.0,
        grid_y_km=0.0,
        delivery_radius_km=12.0,
    )
    create_restaurant(
        name="Pizza Rim",
        cuisine="PIZZA",
        grid_x_km=0.0,
        grid_y_km=9.0,
        delivery_radius_km=12.0,
    )
    create_restaurant(
        name="Sushi Nine",
        cuisine="SUSHI",
        grid_x_km=1.0,
        grid_y_km=0.0,
        delivery_radius_km=12.0,
    )

    response = api_client.list_eligible_restaurants(
        ns.program["id"],
        TEST_USERS["program_admin_headers"],
        params={"delivery_location_id": ns.location["id"]},
    )
    data, meta = validate_paginated(response)

    names = [row["name"] for row in data]
    assert names == ["Thai Garden", "Salad Edge"], (
        "Thai Garden sits at 5.000 km and Salad Edge at exactly the 8.0 km "
        f"ceiling; Pizza Rim at 9.000 km and Sushi Nine's cuisine are out. Got {names}"
    )
    assert meta["total_count"] == 2


def test_placement_admits_the_eight_km_restaurant_and_refuses_the_nine_km_one():
    """Equality with the effective limit passes at placement, 9.000 km does not.

    PRD §3.4: "the effective limit for that restaurant, which is the smaller of
    the program's `max_delivery_radius_km` and the restaurant's own
    `delivery_radius_km`. Equality with the effective limit passes."

    Design: Difficulty/boundary_precision_check/delivery_radius_exactly_8_000_km_eligible_while_9_000_km_excluded
    """
    ns = setup_scenario(program_overrides={"eligible_cuisines": ["THAI", "SALAD", "PIZZA"]})
    salad_edge = create_restaurant(
        name="Salad Edge",
        cuisine="SALAD",
        grid_x_km=8.0,
        grid_y_km=0.0,
        delivery_radius_km=12.0,
    )
    pizza_rim = create_restaurant(
        name="Pizza Rim",
        cuisine="PIZZA",
        grid_x_km=0.0,
        grid_y_km=9.0,
        delivery_radius_km=12.0,
    )
    ben, ben_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Ben Barnes", "email": "ben@acme.test"}
    )

    in_range = draft_order(ns.employee, ns.period, salad_edge, ns.location)
    in_range = place_order(in_range, ns.employee)
    assert in_range["fulfillment_status"] == "PLACED"
    assert in_range["covered_base_cents"] == 1787
    assert in_range["employer_covered_cents"] == 1787
    assert in_range["employee_card_cents"] == 0

    out_of_range = draft_order(ben, ben_period, pizza_rim, ns.location)
    response = place_order_raw(out_of_range, ben)
    validate_error(response, ApiErrorId.ERR_RESTAURANT_OUT_OF_RANGE)

    assert read_order(out_of_range["id"])["fulfillment_status"] == "DRAFT"
    assert read_period(ben_period["id"])["reserved_cents"] == 0


def _window_scenario():
    """One program with three enrolled employees, each with an OPEN period."""
    ns = setup_scenario()
    ns.ben, ns.ben_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Ben Barnes", "email": "ben@acme.test"}
    )
    ns.cleo, ns.cleo_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Cleo Chen", "email": "cleo@acme.test"}
    )
    return ns


def test_eligible_window_admits_the_start_minute_and_the_last_minute_before_the_end():
    """Minute 660 and minute 839 are both inside the half-open 660-to-840 window.

    PRD §3.2: "The window is half-open: an order requested exactly at the start
    minute is admitted, and one requested exactly at the end minute is refused."

    Design: Difficulty/boundary_precision_check/eligible_window_half_open_admits_minute_660_and_839_but_refuses_840
    """
    ns = _window_scenario()

    at_start = draft_order(
        ns.employee,
        ns.period,
        ns.restaurant,
        ns.location,
        requested_delivery_at="2026-08-03T11:00:00Z",
    )
    at_start = place_order(at_start, ns.employee)
    assert at_start["fulfillment_status"] == "PLACED"
    assert at_start["settlement_status"] == "SPLIT_AUTHORIZED"

    last_minute = draft_order(
        ns.ben,
        ns.ben_period,
        ns.restaurant,
        ns.location,
        requested_delivery_at="2026-08-03T13:59:00Z",
    )
    last_minute = place_order(last_minute, ns.ben)
    assert last_minute["fulfillment_status"] == "PLACED"


def test_eligible_window_refuses_the_end_minute_exactly():
    """Minute 840 is the excluded end of the window and reserves nothing.

    PRD §2.10: "The minute-of-day of `requested_delivery_at` lies in the
    half-open eligible window — otherwise `ERR_OUTSIDE_ELIGIBLE_WINDOW` (422).
    Applies to placement."

    Design: Difficulty/boundary_precision_check/eligible_window_half_open_admits_minute_660_and_839_but_refuses_840
    """
    ns = _window_scenario()

    at_start = draft_order(
        ns.employee,
        ns.period,
        ns.restaurant,
        ns.location,
        requested_delivery_at="2026-08-03T11:00:00Z",
    )
    place_order(at_start, ns.employee)
    last_minute = draft_order(
        ns.ben,
        ns.ben_period,
        ns.restaurant,
        ns.location,
        requested_delivery_at="2026-08-03T13:59:00Z",
    )
    place_order(last_minute, ns.ben)

    at_end = draft_order(
        ns.cleo,
        ns.cleo_period,
        ns.restaurant,
        ns.location,
        requested_delivery_at="2026-08-03T14:00:00Z",
    )
    response = place_order_raw(at_end, ns.cleo)
    validate_error(response, ApiErrorId.ERR_OUTSIDE_ELIGIBLE_WINDOW)

    assert read_order(at_end["id"])["fulfillment_status"] == "DRAFT"
    assert read_period(ns.cleo_period["id"])["reserved_cents"] == 0
    assert read_period(ns.period["id"])["reserved_cents"] == 1787
    assert read_period(ns.ben_period["id"])["reserved_cents"] == 1787
