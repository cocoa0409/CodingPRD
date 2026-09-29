"""Two orthogonal overlap tests: half-open restaurant capacity, closed dock windows."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_employee_with_period,
    api_client,
    create_group_order_payload,
    create_location,
    create_restaurant,
    draft_order,
    get_success_data,
    lock_group_order,
    make_employee_headers,
    place_order,
    read_group_order,
    read_order,
    read_period,
    setup_program_base,
    validate_error,
    validate_paginated,
)

_CUTOFF = "2026-08-04T11:00:00Z"
_CLOCK = "2026-08-04T10:00:00Z"


def _locked_group(ns, organizer, period, restaurant, location, window_start, window_end):
    """Create a group order, attach and place its organiser's member order, lock."""
    group_order = get_success_data(
        api_client.create_group_order(
            create_group_order_payload(
                ns.program["id"],
                organizer["id"],
                restaurant["id"],
                location["id"],
                cutoff_at=_CUTOFF,
                window_start=window_start,
                window_end=window_end,
                per_person_limit_cents=3000,
            ),
            make_employee_headers(organizer["id"]),
        )
    )
    order = draft_order(
        organizer,
        period,
        restaurant,
        location,
        group_order_id=group_order["id"],
        requested_delivery_at=window_start,
    )
    order = place_order(order, organizer)
    lock_group_order(group_order, organizer)
    return group_order, order


def _submit(group_order, organizer):
    return api_client.submit_group_order(
        group_order["id"], make_employee_headers(organizer["id"])
    )


def _three_docks_one_restaurant():
    ns = setup_program_base(clock=_CLOCK)
    ns.annex = create_location(
        ns.program["id"], label="Annex Dock", grid_x_km=1.0, grid_y_km=1.0
    )
    ns.west = create_location(
        ns.program["id"], label="West Dock", grid_x_km=2.0, grid_y_km=0.0
    )
    ns.ada, ns.ada_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Ada Lovelace", "email": "ada@acme.test"}
    )
    ns.ben, ns.ben_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Ben Barnes", "email": "ben@acme.test"}
    )
    ns.cleo, ns.cleo_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Cleo Chen", "email": "cleo@acme.test"}
    )
    return ns


def test_touching_half_open_windows_consume_no_restaurant_capacity():
    """A window starting exactly when another ends does not intersect it.

    PRD §3.6: "Because the intervals are half-open, a window that begins at
    exactly the instant another ends does not intersect it and consumes no
    capacity."

    Design: Difficulty/resource_temporal_overlap/restaurant_capacity_half_open_windows_touch_at_1230_without_overlapping
    """
    ns = _three_docks_one_restaurant()
    first, _ = _locked_group(
        ns,
        ns.ada,
        ns.ada_period,
        ns.restaurant,
        ns.location,
        "2026-08-04T12:00:00Z",
        "2026-08-04T12:30:00Z",
    )
    second, _ = _locked_group(
        ns,
        ns.ben,
        ns.ben_period,
        ns.restaurant,
        ns.annex,
        "2026-08-04T12:30:00Z",
        "2026-08-04T13:00:00Z",
    )

    assert get_success_data(_submit(first, ns.ada))["status"] == "SUBMITTED"
    touching = get_success_data(_submit(second, ns.ben))
    assert touching["status"] == "SUBMITTED", (
        "12:30 to 13:00 touches 12:00 to 12:30 without overlapping it"
    )
    assert touching["allocated_delivery_fee_cents"] == 1250


def test_a_genuinely_overlapping_window_exceeds_the_restaurant_capacity_of_one():
    """A third window that straddles the first is refused at rank 21, not rank 20.

    PRD §3.6: "Count the already-`SUBMITTED` group orders at the same restaurant
    whose interval from `window_start` up to but excluding `window_end` intersects
    this group order's interval on the same basis. That count must be strictly
    below the restaurant's `max_concurrent_group_deliveries`, or the submission is
    `ERR_RESTAURANT_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/restaurant_capacity_half_open_windows_touch_at_1230_without_overlapping
    """
    ns = _three_docks_one_restaurant()
    first, _ = _locked_group(
        ns, ns.ada, ns.ada_period, ns.restaurant, ns.location,
        "2026-08-04T12:00:00Z", "2026-08-04T12:30:00Z",
    )
    second, _ = _locked_group(
        ns, ns.ben, ns.ben_period, ns.restaurant, ns.annex,
        "2026-08-04T12:30:00Z", "2026-08-04T13:00:00Z",
    )
    third, third_order = _locked_group(
        ns, ns.cleo, ns.cleo_period, ns.restaurant, ns.west,
        "2026-08-04T12:15:00Z", "2026-08-04T12:45:00Z",
    )

    get_success_data(_submit(first, ns.ada))
    get_success_data(_submit(second, ns.ben))

    response = _submit(third, ns.cleo)
    error = validate_error(response, ApiErrorId.ERR_RESTAURANT_CAPACITY_EXCEEDED)
    assert error["error_id"] != ApiErrorId.ERR_DOCK_WINDOW_CONFLICT.value, (
        "West Dock is unoccupied, so only the restaurant ceiling is breached"
    )

    assert read_group_order(third["id"])["status"] == "LOCKED"
    assert read_order(third_order["id"])["delivery_fee_cents"] == 0
    assert read_period(ns.cleo_period["id"])["reserved_cents"] == 1188


def _one_dock_two_restaurants():
    ns = setup_program_base(
        clock=_CLOCK, program_overrides={"eligible_cuisines": ["THAI", "SALAD"]}
    )
    ns.salad_edge = create_restaurant(
        name="Salad Edge",
        cuisine="SALAD",
        grid_x_km=8.0,
        grid_y_km=0.0,
        delivery_radius_km=12.0,
        max_concurrent_group_deliveries=2,
    )
    ns.ada, ns.ada_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Ada Lovelace", "email": "ada@acme.test"}
    )
    ns.ben, ns.ben_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Ben Barnes", "email": "ben@acme.test"}
    )
    ns.cleo, ns.cleo_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Cleo Chen", "email": "cleo@acme.test"}
    )
    return ns


def test_the_dock_buffer_makes_a_window_starting_at_1245_collide():
    """A 12:00-to-12:30 delivery holds the dock through 12:45 inclusive.

    PRD §3.6: "This group order occupies its dock from `window_start` through
    `window_end` plus the dock's `dock_buffer_minutes`, inclusive at both ends. If
    any other `SUBMITTED` group order occupies the same dock over an interval
    computed the same way and the two intervals share even a single instant, the
    submission is `ERR_DOCK_WINDOW_CONFLICT`; the dock admits one consolidated
    delivery at a time regardless of any capacity number."

    Design: Difficulty/resource_temporal_overlap/dock_closed_interval_plus_15_minute_buffer_collides_at_1245_but_not_at_1246
    """
    ns = _one_dock_two_restaurants()
    first, _ = _locked_group(
        ns, ns.ada, ns.ada_period, ns.restaurant, ns.location,
        "2026-08-04T12:00:00Z", "2026-08-04T12:30:00Z",
    )
    colliding, colliding_order = _locked_group(
        ns, ns.ben, ns.ben_period, ns.salad_edge, ns.location,
        "2026-08-04T12:45:00Z", "2026-08-04T13:15:00Z",
    )

    assert get_success_data(_submit(first, ns.ada))["status"] == "SUBMITTED"

    response = _submit(colliding, ns.ben)
    error = validate_error(response, ApiErrorId.ERR_DOCK_WINDOW_CONFLICT)
    assert error["error_id"] != ApiErrorId.ERR_RESTAURANT_CAPACITY_EXCEEDED.value, (
        "Salad Edge admits two concurrent deliveries; it is the dock that clashes"
    )

    assert read_group_order(colliding["id"])["status"] == "LOCKED"
    assert read_group_order(colliding["id"])["allocated_delivery_fee_cents"] == 0
    assert read_order(colliding_order["id"])["delivery_fee_cents"] == 0


def test_one_minute_past_the_buffered_end_clears_the_dock():
    """12:46 misses the buffered close of 12:45 by a single minute.

    PRD §3.1: "`dock_buffer_minutes`, the minutes of exclusive dock occupancy
    padded on after a group delivery window ends. The buffer is optional, defaults
    to 15, and must be at least 0 and at most 120."

    Design: Difficulty/resource_temporal_overlap/dock_closed_interval_plus_15_minute_buffer_collides_at_1245_but_not_at_1246
    """
    ns = _one_dock_two_restaurants()
    first, first_order = _locked_group(
        ns, ns.ada, ns.ada_period, ns.restaurant, ns.location,
        "2026-08-04T12:00:00Z", "2026-08-04T12:30:00Z",
    )
    colliding, _ = _locked_group(
        ns, ns.ben, ns.ben_period, ns.salad_edge, ns.location,
        "2026-08-04T12:45:00Z", "2026-08-04T13:15:00Z",
    )
    clearing, clearing_order = _locked_group(
        ns, ns.cleo, ns.cleo_period, ns.salad_edge, ns.location,
        "2026-08-04T12:46:00Z", "2026-08-04T13:16:00Z",
    )

    get_success_data(_submit(first, ns.ada))
    validate_error(_submit(colliding, ns.ben), ApiErrorId.ERR_DOCK_WINDOW_CONFLICT)
    assert get_success_data(_submit(clearing, ns.cleo))["status"] == "SUBMITTED"

    assert read_group_order(first["id"])["allocated_delivery_fee_cents"] == 1250
    assert read_group_order(clearing["id"])["allocated_delivery_fee_cents"] == 1250
    assert read_group_order(colliding["id"])["allocated_delivery_fee_cents"] == 0
    assert read_order(first_order["id"])["delivery_fee_cents"] == 1250
    assert read_order(clearing_order["id"])["delivery_fee_cents"] == 1250


def _two_docks_one_spacious_restaurant():
    ns = setup_program_base(
        clock=_CLOCK,
        program_overrides={"eligible_cuisines": ["SALAD"]},
        restaurant_overrides={
            "name": "Salad Edge",
            "cuisine": "SALAD",
            "grid_x_km": 8.0,
            "grid_y_km": 0.0,
            "delivery_radius_km": 12.0,
            "max_concurrent_group_deliveries": 2,
        },
    )
    ns.annex = create_location(
        ns.program["id"], label="Annex Dock", grid_x_km=1.0, grid_y_km=1.0
    )
    ns.ada, ns.ada_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Ada Lovelace", "email": "ada@acme.test"}
    )
    ns.ben, ns.ben_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Ben Barnes", "email": "ben@acme.test"}
    )
    ns.cleo, ns.cleo_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Cleo Chen", "email": "cleo@acme.test"}
    )
    return ns


def test_a_dock_clash_is_reported_even_though_the_restaurant_has_room():
    """Rank 20 fires before rank 21 when both tests would have something to say.

    PRD §3.6: "The consequence is that the very same pair of adjacent windows can
    be perfectly legal for restaurant capacity and simultaneously illegal for the
    dock, and both tests must be applied independently."

    Design: Difficulty/resource_temporal_overlap/dock_conflict_at_priority_20_masks_available_restaurant_capacity_at_priority_21
    """
    ns = _two_docks_one_spacious_restaurant()
    first, _ = _locked_group(
        ns, ns.ada, ns.ada_period, ns.restaurant, ns.location,
        "2026-08-04T12:00:00Z", "2026-08-04T12:30:00Z",
    )
    same_dock, same_dock_order = _locked_group(
        ns, ns.ben, ns.ben_period, ns.restaurant, ns.location,
        "2026-08-04T12:15:00Z", "2026-08-04T12:45:00Z",
    )

    assert get_success_data(_submit(first, ns.ada))["status"] == "SUBMITTED"

    error = validate_error(
        _submit(same_dock, ns.ben), ApiErrorId.ERR_DOCK_WINDOW_CONFLICT
    )
    assert error["error_id"] != ApiErrorId.ERR_RESTAURANT_CAPACITY_EXCEEDED.value

    assert read_group_order(same_dock["id"])["status"] == "LOCKED"
    assert read_order(same_dock_order["id"])["delivery_fee_cents"] == 0


def test_the_identical_window_at_a_second_dock_submits_within_the_capacity_of_two():
    """Capacity 2 admits two overlapping windows once the docks differ.

    PRD §2.10: "Overlapping submitted group orders at the restaurant remain below
    its concurrency ceiling — otherwise `ERR_RESTAURANT_CAPACITY_EXCEEDED` (409).
    Applies to group-order submission."

    Design: Difficulty/resource_temporal_overlap/dock_conflict_at_priority_20_masks_available_restaurant_capacity_at_priority_21
    """
    ns = _two_docks_one_spacious_restaurant()
    first, _ = _locked_group(
        ns, ns.ada, ns.ada_period, ns.restaurant, ns.location,
        "2026-08-04T12:00:00Z", "2026-08-04T12:30:00Z",
    )
    same_dock, _ = _locked_group(
        ns, ns.ben, ns.ben_period, ns.restaurant, ns.location,
        "2026-08-04T12:15:00Z", "2026-08-04T12:45:00Z",
    )
    other_dock, _ = _locked_group(
        ns, ns.cleo, ns.cleo_period, ns.restaurant, ns.annex,
        "2026-08-04T12:15:00Z", "2026-08-04T12:45:00Z",
    )

    get_success_data(_submit(first, ns.ada))
    validate_error(_submit(same_dock, ns.ben), ApiErrorId.ERR_DOCK_WINDOW_CONFLICT)
    assert get_success_data(_submit(other_dock, ns.cleo))["status"] == "SUBMITTED"

    response = api_client.list_group_orders(
        TEST_USERS["program_admin_headers"],
        params={"restaurant_id": ns.restaurant["id"]},
    )
    rows, _meta = validate_paginated(response)
    submitted = [row for row in rows if row["status"] == "SUBMITTED"]
    assert len(submitted) == 2, (
        f"two overlapping windows fit under a ceiling of 2, got {len(submitted)}"
    )
