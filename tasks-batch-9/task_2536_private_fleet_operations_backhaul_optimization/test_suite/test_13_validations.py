"""Declared validations: ordered temporal gates, sequence rules and terminal lockdowns."""

from test_helpers import (
    MANAGER,
    PAYROLL,
    PLANNER,
    ApiErrorId,
    add_delivery_stop,
    add_other_stop,
    assign_resources,
    close_out_trip,
    dispatch_trip,
    make_driver_headers,
    new_backhaul_offer,
    new_domicile,
    new_driver,
    new_order,
    new_pay_plan,
    new_route_posting,
    new_store,
    new_tractor,
    new_trailer,
    new_trip,
    place_bid,
    plan_trip,
    read_offer,
    read_posting,
    read_store,
    read_tractor,
    read_trip,
    review_offer,
    run_stop,
    set_clock,
    setup_base_fleet,
    validate_error,
    validate_paginated,
    validate_success,
)


# ------------------------------------- dock hours before the merchandising window ----


def _candidate_delivery(order_window_start, arrival, departure, planned_start):
    """A staffed DRAFT trip with one delivery at a store receiving from 08:00 to 17:00."""
    set_clock()
    domicile = new_domicile(domicile_code="DOM-V1")
    plan = new_pay_plan(plan_code="MILE-C")
    store = new_store(store_code="S-5001", dock_open_minute=480, dock_close_minute=1020)
    driver = new_driver(domicile["id"], plan["id"], driver_code="D-V1",
                        seniority_date="2019-03-01")
    tractor = new_tractor(domicile["id"], unit_code="TR-V1")
    trailer = new_trailer(domicile["id"], trailer_code="TL-V1")
    order = new_order(store["id"], requested_window_start=order_window_start,
                      requested_window_end="2026-08-20T18:00:00Z")
    trip = new_trip(domicile["id"], trip_code="TRIP-V1", planned_start_at=planned_start)
    stop = add_delivery_stop(trip["id"], store["id"], order["id"], 1, arrival, departure,
                             120, 100, 600)
    assign_resources(trip["id"], driver["id"], tractor["id"], trailer["id"])
    return {"store": store, "order": order, "trip": trip, "stop": stop}


def test_a_stop_that_breaks_both_temporal_fits_reports_the_dock_code(api):
    """PRD §3.5: "First **dock hours**: convert the stop's `scheduled_arrival_at` and
    `scheduled_departure_at` to minutes of the UTC day by taking the hour times sixty plus
    the minute. The stop is refused with `ERR_DOCK_HOURS_VIOLATION` if the arrival and the
    departure do not fall on the same UTC calendar date, or if the arrival minute is earlier
    than the store's `dock_open_minute`, or if the departure minute is later than the store's
    `dock_close_minute`. Second **merchandising window fit**, with both edges inclusive
    against the order: the stop is refused with `ERR_DELIVERY_WINDOW_VIOLATION` if
    `scheduled_arrival_at` is earlier than the order's `requested_window_start` or
    `scheduled_departure_at` is later than the order's `requested_window_end`. A stop that
    violates both of these reports the dock-hours code, because dock hours are checked
    first." And PRD §2.10: "A cascade never stops halfway. If the operation is rejected at
    any precedence level, none of the links fire at all."

    Design: Corner/validations/dock_hours_are_checked_before_the_delivery_window
    """
    # An occupation of [06:00, 07:15] precedes both the 08:00 dock opening and the
    # order's 09:00 window opening.
    ctx = _candidate_delivery("2026-08-20T09:00:00Z", "2026-08-20T06:00:00Z",
                              "2026-08-20T07:15:00Z", "2026-08-20T04:00:00Z")
    validate_error(
        api.plan_trip(ctx["trip"]["id"], PLANNER),
        ApiErrorId.ERR_DOCK_HOURS_VIOLATION,
        422,
    )
    assert read_trip(ctx["trip"]["id"])["plan_status"] == "DRAFT"
    order = validate_success(api.get_order(ctx["order"]["id"], PLANNER))
    assert order["status"] == "UNSCHEDULED"
    assert validate_success(api.get_store(ctx["store"]["id"], PLANNER))["open_scheduled_cases"] == 0


def test_an_occupation_inside_the_dock_day_falls_through_to_the_window_code(api):
    """PRD §3.5: "Second **merchandising window fit**, with both edges inclusive against the
    order: the stop is refused with `ERR_DELIVERY_WINDOW_VIOLATION` if
    `scheduled_arrival_at` is earlier than the order's `requested_window_start` or
    `scheduled_departure_at` is later than the order's `requested_window_end`. A stop that
    violates both of these reports the dock-hours code, because dock hours are checked
    first." And PRD §3.5: "Committing the schedule is a `FleetPlanner` act that takes the
    trip `DRAFT → PLANNED`, and it is where the temporal contract with the stores is finally
    enforced."

    Design: Corner/validations/dock_hours_are_checked_before_the_delivery_window
    """
    # [09:30, 10:45] sits inside minutes 480 to 1020 but opens before the order's 11:00.
    ctx = _candidate_delivery("2026-08-20T11:00:00Z", "2026-08-20T09:30:00Z",
                              "2026-08-20T10:45:00Z", "2026-08-20T07:00:00Z")
    validate_error(
        api.plan_trip(ctx["trip"]["id"], PLANNER),
        ApiErrorId.ERR_DELIVERY_WINDOW_VIOLATION,
        422,
    )

    validate_success(api.delete_trip_stop(ctx["trip"]["id"], ctx["stop"]["id"], PLANNER))
    add_delivery_stop(ctx["trip"]["id"], ctx["store"]["id"], ctx["order"]["id"], 1,
                      "2026-08-20T11:30:00Z", "2026-08-20T12:45:00Z", 120, 100, 600)
    # [11:30, 12:45] now fits the dock day and the order window alike.
    assert plan_trip(ctx["trip"]["id"])["plan_status"] == "PLANNED"


# ---------------------------------------------- contiguous, non-decreasing stops ----


def _empty_draft_trip():
    set_clock()
    domicile = new_domicile(domicile_code="DOM-V2")
    store = new_store(store_code="S-5002")
    order = new_order(store["id"])
    trip = new_trip(domicile["id"], trip_code="TRIP-V2",
                    planned_start_at="2026-08-20T06:00:00Z")
    return store, order, trip


def _delivery_body(store, order, sequence, arrival, departure):
    return {
        "sequence": sequence,
        "stop_type": "DELIVERY",
        "store_id": store["id"],
        "replenishment_order_id": order["id"],
        "scheduled_arrival_at": arrival,
        "scheduled_departure_at": departure,
        "drive_minutes_from_prev": 120,
        "miles_from_prev": 100,
        "segment_loaded": True,
        "cases": 600,
    }


def test_the_first_stop_of_a_trip_cannot_be_numbered_two(api):
    """PRD §3.4: "Each append supplies a `sequence` that must be exactly one greater than the
    highest sequence the trip already holds, so the first stop is 1 and the numbering stays
    contiguous; any other value is `ERR_STOP_SEQUENCE_DISORDER`."

    Design: Corner/validations/stop_sequences_must_be_contiguous_and_instants_non_decreasing
    """
    store, order, trip = _empty_draft_trip()
    validate_error(
        api.add_trip_stop(
            trip["id"],
            _delivery_body(store, order, 2, "2026-08-20T08:00:00Z", "2026-08-20T09:15:00Z"),
            PLANNER,
        ),
        ApiErrorId.ERR_STOP_SEQUENCE_DISORDER,
        422,
    )
    assert read_trip(trip["id"])["stop_count"] == 0

    first = add_delivery_stop(trip["id"], store["id"], order["id"], 1,
                              "2026-08-20T08:00:00Z", "2026-08-20T09:15:00Z", 120, 100, 600)
    assert first["sequence"] == 1


def test_an_arrival_may_equal_but_never_precede_the_previous_departure(api):
    """PRD §3.4: "The stop's dock occupation is given by `scheduled_arrival_at` and
    `scheduled_departure_at`, the departure strictly after the arrival, and the arrival must
    not be earlier than the previous stop's `scheduled_departure_at` — a stop that would run
    backwards in time relative to its predecessor is also `ERR_STOP_SEQUENCE_DISORDER`." And
    PRD §3.4: "For a `DROP_OFF` it is a flat twenty minutes, and for a `FUEL` stop a flat
    twenty-five minutes."

    Design: Corner/validations/stop_sequences_must_be_contiguous_and_instants_non_decreasing
    """
    store, order, trip = _empty_draft_trip()
    add_delivery_stop(trip["id"], store["id"], order["id"], 1, "2026-08-20T08:00:00Z",
                      "2026-08-20T09:15:00Z", 120, 100, 600)
    # 09:00 runs backwards against stop 1's 09:15 departure.
    validate_error(
        api.add_trip_stop(
            trip["id"],
            {
                "sequence": 2,
                "stop_type": "FUEL",
                "scheduled_arrival_at": "2026-08-20T09:00:00Z",
                "scheduled_departure_at": "2026-08-20T09:25:00Z",
                "drive_minutes_from_prev": 20,
                "miles_from_prev": 15,
                "segment_loaded": False,
            },
            PLANNER,
        ),
        ApiErrorId.ERR_STOP_SEQUENCE_DISORDER,
        422,
    )

    touching = add_other_stop(trip["id"], "FUEL", 2, "2026-08-20T09:15:00Z",
                              "2026-08-20T09:40:00Z", 20, 15)
    assert touching["sequence"] == 2
    assert touching["service_minutes"] == 25

    listed, _meta = validate_paginated(api.list_stops_of_trip(trip["id"], PLANNER))
    assert [stop["sequence"] for stop in listed] == [1, 2]


# ---------------------------------------------- execution order at the stop level ----


def _dispatched_trip_with_two_stops():
    ctx = setup_base_fleet("v3")
    trip = new_trip(ctx["domicile"]["id"], trip_code="TRIP-V3",
                    planned_start_at="2026-08-20T06:00:00Z")
    first = add_delivery_stop(trip["id"], ctx["store"]["id"], ctx["order"]["id"], 1,
                              "2026-08-20T08:00:00Z", "2026-08-20T09:15:00Z", 120, 100, 600)
    second = add_other_stop(trip["id"], "FUEL", 2, "2026-08-20T10:00:00Z",
                            "2026-08-20T10:25:00Z", 45, 38)
    assign_resources(trip["id"], ctx["driver"]["id"], ctx["tractor"]["id"],
                     ctx["trailer"]["id"])
    plan_trip(trip["id"])
    dispatch_trip(trip["id"])
    return ctx, trip, first, second


def test_the_second_stop_cannot_be_arrived_while_the_first_is_still_planned(api):
    """PRD §3.7: "Stops must be worked in order: every stop of the same trip with a lower
    `sequence` must already be `COMPLETED` or `SKIPPED`, otherwise the check-in is refused
    with `ERR_STOP_SEQUENCE_CONFLICT`." And PRD §3.7: "The **first** arrival on a trip that
    is still `DISPATCHED` bubbles the parent upward — the trip moves `DISPATCHED →
    IN_PROGRESS` as a consequence of the child stop's transition, and the stop's own
    `version` advances."

    Design: Corner/validations/arriving_at_a_later_stop_first_is_a_sequence_conflict
    """
    ctx, trip, _first, second = _dispatched_trip_with_two_stops()
    driver_headers = make_driver_headers(ctx["driver"]["id"])
    validate_error(
        api.arrive_at_stop(second["id"], driver_headers),
        ApiErrorId.ERR_STOP_SEQUENCE_CONFLICT,
        409,
    )
    # The refused check-in did not bubble the parent.
    assert read_trip(trip["id"])["plan_status"] == "DISPATCHED"
    assert validate_success(api.get_trip_stop(second["id"], MANAGER))["status"] == "PLANNED"


def test_an_arrived_predecessor_is_not_yet_a_terminal_predecessor(api):
    """PRD §3.7: "Stops must be worked in order: every stop of the same trip with a lower
    `sequence` must already be `COMPLETED` or `SKIPPED`, otherwise the check-in is refused
    with `ERR_STOP_SEQUENCE_CONFLICT`." And PRD §3.7: "Checking out of a stop takes it
    `ARRIVED → COMPLETED` and may record an `actual_departure_at` instant."

    Design: Corner/validations/arriving_at_a_later_stop_first_is_a_sequence_conflict
    """
    ctx, _trip, first, second = _dispatched_trip_with_two_stops()
    driver_headers = make_driver_headers(ctx["driver"]["id"])
    arrived = validate_success(api.arrive_at_stop(first["id"], driver_headers))
    assert arrived["status"] == "ARRIVED"

    validate_error(
        api.arrive_at_stop(second["id"], driver_headers),
        ApiErrorId.ERR_STOP_SEQUENCE_CONFLICT,
        409,
    )

    done = validate_success(api.complete_stop(first["id"], {}, driver_headers))
    assert done["status"] == "COMPLETED"
    unlocked = validate_success(api.arrive_at_stop(second["id"], driver_headers))
    assert unlocked["status"] == "ARRIVED"


# ------------------------------------- the trailer type before the trailer capacity ----


def _refrigerated_trip_and_three_trailers():
    set_clock()
    domicile = new_domicile(domicile_code="DOM-V4")
    plan = new_pay_plan(plan_code="MILE-C")
    store = new_store(store_code="S-5004")
    driver = new_driver(domicile["id"], plan["id"], driver_code="D-V4",
                        seniority_date="2019-03-01")
    tractor = new_tractor(domicile["id"], unit_code="TR-V4")
    dry = new_trailer(domicile["id"], trailer_code="TL-V4-DRY", trailer_type="DRY_VAN",
                      capacity_cases=1800)
    tight = new_trailer(domicile["id"], trailer_code="TL-V4-RFR", trailer_type="REEFER",
                        capacity_cases=599)
    exact = new_trailer(domicile["id"], trailer_code="TL-V4-R600", trailer_type="REEFER",
                        capacity_cases=600)
    order = new_order(store["id"], temperature_mode="REFRIGERATED")
    trip = new_trip(domicile["id"], trip_code="TRIP-V4",
                    planned_start_at="2026-08-20T06:00:00Z")
    add_delivery_stop(trip["id"], store["id"], order["id"], 1, "2026-08-20T08:00:00Z",
                      "2026-08-20T09:15:00Z", 120, 100, 600)
    return {"driver": driver, "tractor": tractor, "dry": dry, "tight": tight,
            "exact": exact, "trip": trip}


def _assign(api, ctx, trailer):
    return api.assign_trip_resources(
        ctx["trip"]["id"],
        {"driver_id": ctx["driver"]["id"], "tractor_id": ctx["tractor"]["id"],
         "trailer_id": trailer["id"]},
        MANAGER,
    )


def test_a_roomy_dry_van_reports_the_temperature_objection_first(api):
    """PRD §3.5: "Finally the **capacity and temperature** gates: the trip's `peak_case_load`
    must not exceed the assigned trailer's `capacity_cases`, where equality passes and any
    excess is `ERR_TRAILER_CAPACITY_EXCEEDED`; and if any `DELIVERY` stop's order has a
    `temperature_mode` of `REFRIGERATED`, the assigned trailer's `trailer_type` must be
    `REEFER`, else `ERR_TEMPERATURE_MODE_MISMATCH`." And PRD §2.10: "A cascade never stops
    halfway. If the operation is rejected at any precedence level, none of the links fire at
    all."

    Design: Corner/validations/temperature_mode_is_reported_before_capacity_and_capacity_is_inclusive
    """
    ctx = _refrigerated_trip_and_three_trailers()
    # 1800 cases of room, but the wrong box for refrigerated freight.
    validate_error(_assign(api, ctx, ctx["dry"]), ApiErrorId.ERR_TEMPERATURE_MODE_MISMATCH, 422)
    assert validate_success(api.get_trailer(ctx["dry"]["id"], MANAGER))["status"] == "AVAILABLE"
    assert read_trip(ctx["trip"]["id"])["trailer_id"] is None


def test_a_reefer_one_case_short_fails_where_an_exact_fit_passes(api):
    """PRD §3.5: "Finally the **capacity and temperature** gates: the trip's `peak_case_load`
    must not exceed the assigned trailer's `capacity_cases`, where equality passes and any
    excess is `ERR_TRAILER_CAPACITY_EXCEEDED`; and if any `DELIVERY` stop's order has a
    `temperature_mode` of `REFRIGERATED`, the assigned trailer's `trailer_type` must be
    `REEFER`, else `ERR_TEMPERATURE_MODE_MISMATCH`." And PRD §3.5: "The plan gate closes with
    the trailer capacity check on `peak_case_load` and a fresh hours-of-service evaluation
    against the driver's counters at that instant, using the same three ceilings and the same
    pinned drive-duty-weekly order as the assignment gate."

    Design: Corner/validations/temperature_mode_is_reported_before_capacity_and_capacity_is_inclusive
    """
    ctx = _refrigerated_trip_and_three_trailers()
    validate_error(_assign(api, ctx, ctx["tight"]), ApiErrorId.ERR_TRAILER_CAPACITY_EXCEEDED, 422)
    assert validate_success(api.get_trailer(ctx["tight"]["id"], MANAGER))["status"] == "AVAILABLE"

    staffed = validate_success(_assign(api, ctx, ctx["exact"]))
    assert staffed["trailer_id"] == ctx["exact"]["id"]
    assert staffed["peak_case_load"] == 600

    planned = plan_trip(ctx["trip"]["id"])
    assert planned["plan_status"] == "PLANNED"
    assert planned["peak_case_load"] == 600


# ------------------------------------------- one order, one trip, still schedulable ----


def _two_crews_and_two_orders():
    set_clock()
    domicile = new_domicile(domicile_code="DOM-V5")
    plan = new_pay_plan(plan_code="MILE-C")
    store = new_store(store_code="S-5005")
    crew_a = {
        "driver": new_driver(domicile["id"], plan["id"], driver_code="D-V5A"),
        "tractor": new_tractor(domicile["id"], unit_code="TR-V5A"),
        "trailer": new_trailer(domicile["id"], trailer_code="TL-V5A"),
    }
    crew_b = {
        "driver": new_driver(domicile["id"], plan["id"], driver_code="D-V5B"),
        "tractor": new_tractor(domicile["id"], unit_code="TR-V5B"),
        "trailer": new_trailer(domicile["id"], trailer_code="TL-V5B"),
    }
    first_order = new_order(store["id"])
    second_order = new_order(store["id"])

    taken = new_trip(domicile["id"], trip_code="TRIP-V5A",
                     planned_start_at="2026-08-20T06:00:00Z")
    add_delivery_stop(taken["id"], store["id"], first_order["id"], 1,
                      "2026-08-20T08:00:00Z", "2026-08-20T09:15:00Z", 120, 100, 600)
    assign_resources(taken["id"], crew_a["driver"]["id"], crew_a["tractor"]["id"],
                     crew_a["trailer"]["id"])
    plan_trip(taken["id"])

    rival = new_trip(domicile["id"], trip_code="TRIP-V5B",
                     planned_start_at="2026-08-20T10:00:00Z")
    return {"store": store, "crew_b": crew_b, "first_order": first_order,
            "second_order": second_order, "rival": rival}


def test_an_order_already_carried_elsewhere_is_not_addressable_on_a_second_trip(api):
    """PRD §3.4: "A referenced order that is already attached to a different trip is not
    addressable here and is refused with `ERR_PARENT_MISMATCH`." And PRD §3.4: "An order that
    has not yet been planned onto a trip may be cancelled, optionally with a `reason_code`,
    moving `UNSCHEDULED → CANCELLED`. Any other starting status — `SCHEDULED`, `DELIVERED` or
    already `CANCELLED` — is refused with `ERR_ORDER_NOT_SCHEDULABLE`."

    Design: Corner/validations/an_order_belongs_to_one_trip_and_must_still_be_schedulable_at_plan_time
    """
    ctx = _two_crews_and_two_orders()
    poached = _delivery_body(ctx["store"], ctx["first_order"], 1,
                            "2026-08-20T11:00:00Z", "2026-08-20T12:15:00Z")
    validate_error(
        api.add_trip_stop(ctx["rival"]["id"], poached, PLANNER),
        ApiErrorId.ERR_PARENT_MISMATCH,
        403,
    )
    assert read_trip(ctx["rival"]["id"])["stop_count"] == 0

    # The same order is equally out of reach of the cancellation surface.
    validate_error(
        api.cancel_order(ctx["first_order"]["id"], {"reason_code": "STORE_REQUEST"}, PLANNER),
        ApiErrorId.ERR_ORDER_NOT_SCHEDULABLE,
        409,
    )
    assert validate_success(api.get_order(ctx["first_order"]["id"], PLANNER))["status"] == "SCHEDULED"


def test_an_order_cancelled_under_a_draft_trip_blocks_the_commitment(api):
    """PRD §3.5: "Every `DELIVERY` stop's store must be `ACTIVE`, otherwise
    `ERR_STORE_SUSPENDED`, and every `DELIVERY` stop's order must still be `UNSCHEDULED`,
    otherwise `ERR_ORDER_NOT_SCHEDULABLE`." And PRD §3.4: "The store's `open_scheduled_cases`
    does not move, because an `UNSCHEDULED` order was never inside the ledger's filter to
    begin with."

    Design: Corner/validations/an_order_belongs_to_one_trip_and_must_still_be_schedulable_at_plan_time
    """
    ctx = _two_crews_and_two_orders()
    body = _delivery_body(ctx["store"], ctx["second_order"], 1,
                          "2026-08-20T11:00:00Z", "2026-08-20T12:15:00Z")
    validate_success(api.add_trip_stop(ctx["rival"]["id"], body, PLANNER), 201)
    assert read_trip(ctx["rival"]["id"])["stop_count"] == 1

    # Still UNSCHEDULED while its trip is DRAFT, so the cancellation lands.
    killed = validate_success(api.cancel_order(ctx["second_order"]["id"],
                                     {"reason_code": "STORE_REQUEST"}, PLANNER))
    assert killed["status"] == "CANCELLED"
    ledger = read_store(ctx["store"]["id"])
    assert ledger["open_scheduled_cases"] == 600  # the other trip's order only

    assign_resources(ctx["rival"]["id"], ctx["crew_b"]["driver"]["id"],
                     ctx["crew_b"]["tractor"]["id"], ctx["crew_b"]["trailer"]["id"])
    validate_error(
        api.plan_trip(ctx["rival"]["id"], PLANNER),
        ApiErrorId.ERR_ORDER_NOT_SCHEDULABLE,
        409,
    )
    assert read_trip(ctx["rival"]["id"])["plan_status"] == "DRAFT"


# ------------------------------------------ uniqueness objections sit behind the OCC ----


def _board_with_one_bid():
    set_clock()
    domicile = new_domicile(domicile_code="DOM-V6")
    plan = new_pay_plan(plan_code="MILE-C")
    store = new_store(store_code="S-5006")
    driver = new_driver(domicile["id"], plan["id"], driver_code="D-V6")
    posting = new_route_posting(domicile["id"], route_code="P-6001")
    opening_version = posting["version"]
    bid = place_bid(driver["id"], posting["id"], opening_version)
    assert bid["status"] == "SUBMITTED"
    board = read_posting(posting["id"])
    assert board["bid_count"] == 1
    assert board["version"] == opening_version + 1
    return {"domicile": domicile, "store": store, "driver": driver,
            "posting": posting, "bid": bid, "opening_version": opening_version,
            "current_version": board["version"]}


def test_a_recycled_store_code_is_refused_even_with_different_capacities(api):
    """PRD §3.1: "A `FleetPlanner` registers each receiving location as a store, supplying a
    `store_code` of one to sixteen characters that must be unique across every store in the
    system — a collision is reported as `ERR_DUPLICATE_CODE` — together with a `region_code`
    naming the operating region the location sits in (the fixtures in use exercise `MIDWEST`,
    `SOUTHEAST` and `WEST`, though the field is free text and the backhaul origin matching
    simply compares strings)."

    Design: Corner/validations/duplicate_codes_and_duplicate_bids_are_both_422_after_the_occ_gate
    """
    ctx = _board_with_one_bid()
    clash = validate_error(
        api.create_store(
            {"store_code": "S-5006", "region_code": "SOUTHEAST", "dock_count": 9,
             "cases_per_hour_unload_rate": 1200, "dock_open_minute": 300,
             "dock_close_minute": 1300},
            PLANNER,
        ),
        ApiErrorId.ERR_DUPLICATE_CODE,
        422,
    )
    assert clash["error_id"] == "ERR_DUPLICATE_CODE"
    # The original registration is untouched by the collision.
    original = read_store(ctx["store"]["id"])
    assert original["region_code"] == "MIDWEST"
    assert original["dock_count"] == 2


def test_a_replayed_board_version_is_reported_before_the_duplicate_bid(api):
    """PRD §3.9: "Because a posting is a contended parent, a bid must also carry
    `expected_posting_version`, and a mismatch is `ERR_STALE_POSTING_VERSION`." And PRD §3.9:
    "A driver may hold only one `SUBMITTED` bid per posting; a second is `ERR_DUPLICATE_BID`,
    though a driver whose earlier bid was withdrawn or passed over may bid again."

    Design: Corner/validations/duplicate_codes_and_duplicate_bids_are_both_422_after_the_occ_gate
    """
    ctx = _board_with_one_bid()
    body = {"route_posting_id": ctx["posting"]["id"],
            "expected_posting_version": ctx["opening_version"]}
    driver_headers = make_driver_headers(ctx["driver"]["id"])
    validate_error(
        api.create_route_bid(body, driver_headers),
        ApiErrorId.ERR_STALE_POSTING_VERSION,
        412,
    )

    body["expected_posting_version"] = ctx["current_version"]
    validate_error(
        api.create_route_bid(body, driver_headers),
        ApiErrorId.ERR_DUPLICATE_BID,
        422,
    )

    rows, meta = validate_paginated(
        api.list_route_bids(MANAGER, {"route_posting_id": ctx["posting"]["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx["bid"]["id"]
    assert read_posting(ctx["posting"]["id"])["bid_count"] == 1


# ------------------------------------------- an offer outside review answers nothing ----


def _offer_still_with_the_shipper():
    set_clock()
    store = new_store(store_code="S-5007")
    offer = new_backhaul_offer(store["id"])
    return store, offer


def test_a_proposed_offer_refuses_revise_accept_and_reject_alike(api):
    """PRD §3.6: "Negotiation is a bounded revision loop. Sending an offer back to the shipper
    takes it `UNDER_REVIEW → PROPOSED`, and it is permitted only while `review_round` is below
    3; a fourth attempt is `ERR_REVIEW_ROUND_LIMIT`, and an offer that is not `UNDER_REVIEW`
    is `ERR_OFFER_NOT_UNDER_REVIEW`." And PRD §3.6: "Acceptance belongs to the
    `TransportManager` and carries the most conditions of any offer action. The offer must be
    `UNDER_REVIEW`, otherwise `ERR_OFFER_NOT_UNDER_REVIEW`."

    Design: Corner/validations/an_offer_that_is_not_under_review_refuses_revise_accept_and_reject
    """
    _store, offer = _offer_still_with_the_shipper()
    assert offer["status"] == "PROPOSED"
    validate_error(
        api.revise_offer(offer["id"], {"revenue_cents": 50000}, PLANNER),
        ApiErrorId.ERR_OFFER_NOT_UNDER_REVIEW,
        409,
    )
    validate_error(
        api.accept_offer(offer["id"], MANAGER, {}),
        ApiErrorId.ERR_OFFER_NOT_UNDER_REVIEW,
        409,
    )
    validate_error(
        api.reject_offer(offer["id"], {"reason_code": "TOO_THIN"}, MANAGER),
        ApiErrorId.ERR_OFFER_NOT_UNDER_REVIEW,
        409,
    )
    untouched = read_offer(offer["id"])
    assert untouched["status"] == "PROPOSED"
    assert untouched["review_round"] == 0
    assert untouched["revenue_cents"] == 60000
    # None of the six computed fields were written by a refused call.
    for field in ("variable_cost_cents", "gross_margin_cents", "tier_margin_pct",
                  "commission_cents", "contribution_margin_cents", "margin_pct"):
        assert untouched[field] == 0


def test_a_revision_returns_the_offer_to_the_shipper_and_reprices_it(api):
    """PRD §3.6: "Moving an offer `PROPOSED → UNDER_REVIEW` is what triggers pricing for the
    first time." And PRD §3.6: "The revision may supply any subset of `revenue_cents`,
    `cases`, `deadhead_miles` and `loaded_miles`; supplied values overwrite, omitted values
    are left alone. `review_round` then rises by 1, the full contribution-margin calculation
    re-runs on the revised economics, and — because the offer is by definition no longer
    accepted — any trip that links this offer has its `backhaul_credit_cents` reset to zero."

    Design: Corner/validations/an_offer_that_is_not_under_review_refuses_revise_accept_and_reject
    """
    _store, offer = _offer_still_with_the_shipper()
    priced = review_offer(offer["id"])
    assert priced["status"] == "UNDER_REVIEW"
    assert priced["variable_cost_cents"] == 41500
    assert priced["gross_margin_cents"] == 18500
    assert priced["tier_margin_pct"] == 0.3083
    assert priced["commission_cents"] == 3600
    assert priced["contribution_margin_cents"] == 14900
    assert priced["margin_pct"] == 0.2483

    revised = validate_success(api.revise_offer(offer["id"], {"revenue_cents": 50000}, PLANNER))
    assert revised["status"] == "PROPOSED"
    assert revised["review_round"] == 1
    # Omitted economics are left exactly alone.
    assert revised["cases"] == 500
    assert revised["deadhead_miles"] == 40
    assert revised["loaded_miles"] == 160
    assert revised["variable_cost_cents"] == 41500
    assert revised["gross_margin_cents"] == 8500
    assert revised["tier_margin_pct"] == 0.17
    assert revised["commission_cents"] == 1500
    assert revised["contribution_margin_cents"] == 7000
    assert revised["margin_pct"] == 0.14

    # Back outside review, the same three surfaces close again.
    validate_error(
        api.accept_offer(offer["id"], MANAGER, {}),
        ApiErrorId.ERR_OFFER_NOT_UNDER_REVIEW,
        409,
    )


# ------------------------------------------------ a paid statement is done answering ----


def _accrued_statement(api):
    ctx = setup_base_fleet(
        "v8",
        pay_plan_overrides={"plan_code": "MILE-Z", "minimum_daily_cents": 0},
    )
    trip = new_trip(ctx["domicile"]["id"], trip_code="TRIP-V8",
                    planned_start_at="2026-08-20T06:00:00Z")
    stop = add_delivery_stop(trip["id"], ctx["store"]["id"], ctx["order"]["id"], 1,
                             "2026-08-20T08:00:00Z", "2026-08-20T09:15:00Z", 120, 100, 600)
    assign_resources(trip["id"], ctx["driver"]["id"], ctx["tractor"]["id"],
                     ctx["trailer"]["id"])
    plan_trip(trip["id"])
    dispatch_trip(trip["id"])
    run_stop(stop["id"], ctx["driver"]["id"], cases_handled=600)
    closed = close_out_trip(trip["id"], 120, 195)
    assert closed["settlement_status"] == "ACCRUED"
    assert closed["driver_pay_cents"] == 10000

    rows, _meta = validate_paginated(
        api.list_pay_statements(PAYROLL, {"trip_id": trip["id"]})
    )
    assert len(rows) == 1
    statement = rows[0]
    assert statement["status"] == "ACCRUED"
    assert statement["gross_cents"] == 10000
    assert statement["variant"] == "FINAL_SETTLEMENT"
    assert statement["settlement_reference"] is None
    return ctx, trip, statement


def test_a_settled_statement_cannot_be_settled_twice(api):
    """PRD §3.8: "Settlement is a `PayrollAnalyst` act that records a `settlement_reference`
    and takes the statement `ACCRUED → SETTLED`, and in the same request takes the trip's
    payroll dimension `ACCRUED → SETTLED`. A statement that is not `ACCRUED` is refused with
    `ERR_STATEMENT_NOT_ACCRUED`, and a statement whose trip's payroll dimension is not
    `ACCRUED` is `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/validations/a_settled_or_reversed_statement_refuses_further_payroll_action
    """
    _ctx, trip, statement = _accrued_statement(api)
    paid = validate_success(
        api.settle_pay_statement(statement["id"],
                                 {"settlement_reference": "PAYRUN-2026-34"}, PAYROLL)
    )
    assert paid["status"] == "SETTLED"
    assert paid["settlement_reference"] == "PAYRUN-2026-34"
    assert read_trip(trip["id"])["settlement_status"] == "SETTLED"

    validate_error(
        api.settle_pay_statement(statement["id"],
                                 {"settlement_reference": "PAYRUN-2026-35"}, PAYROLL),
        ApiErrorId.ERR_STATEMENT_NOT_ACCRUED,
        409,
    )
    still = validate_success(api.get_pay_statement(statement["id"], PAYROLL))
    assert still["status"] == "SETTLED"
    assert still["settlement_reference"] == "PAYRUN-2026-34"


def test_a_reversed_statement_refuses_both_reversal_and_settlement(api):
    """PRD §3.8: "Reversal is the money unwind, a `PayrollAnalyst` act with an optional
    `reason_code`, and it is valid from either `ACCRUED` or `SETTLED`; both origins produce an
    identical cascade. The statement moves to `REVERSED`, which is terminal for that
    statement." And PRD §3.8: "A statement in any other status is `ERR_STATEMENT_NOT_ACCRUED`."

    Design: Corner/validations/a_settled_or_reversed_statement_refuses_further_payroll_action
    """
    _ctx, trip, statement = _accrued_statement(api)
    validate_success(
        api.settle_pay_statement(statement["id"],
                                 {"settlement_reference": "PAYRUN-2026-34"}, PAYROLL)
    )
    reversed_row = validate_success(
        api.reverse_pay_statement(statement["id"], {"reason_code": "OVERPAID"}, PAYROLL)
    )
    assert reversed_row["status"] == "REVERSED"
    unwound = read_trip(trip["id"])
    assert unwound["settlement_status"] == "ADJUSTED"
    assert unwound["driver_pay_cents"] == 0

    validate_error(
        api.reverse_pay_statement(statement["id"], {"reason_code": "AGAIN"}, PAYROLL),
        ApiErrorId.ERR_STATEMENT_NOT_ACCRUED,
        409,
    )
    validate_error(
        api.settle_pay_statement(statement["id"],
                                 {"settlement_reference": "PAYRUN-2026-36"}, PAYROLL),
        ApiErrorId.ERR_STATEMENT_NOT_ACCRUED,
        409,
    )
    assert validate_success(api.get_pay_statement(statement["id"], PAYROLL))["status"] == "REVERSED"


# ---------------------------------------- lending a driver takes two arithmetic votes ----


def _lender_and_borrower():
    set_clock()
    plan = new_pay_plan(plan_code="MILE-C")
    source = new_domicile(domicile_code="DOM-V9S", driver_headcount_target=2)
    target = new_domicile(domicile_code="DOM-V9T", driver_headcount_target=3)
    lent = [
        new_driver(source["id"], plan["id"], driver_code="D-V9S%d" % n)
        for n in (1, 2, 3)
    ]
    held = [
        new_driver(target["id"], plan["id"], driver_code="D-V9T%d" % n)
        for n in (1, 2, 3)
    ]
    target_tractor = new_tractor(target["id"], unit_code="TR-V9T")
    target_trailer = new_trailer(target["id"], trailer_code="TL-V9T")
    source_tractor = new_tractor(source["id"], unit_code="TR-V9S")

    store = new_store(store_code="S-5009")
    order = new_order(store["id"])
    trip = new_trip(target["id"], trip_code="TRIP-V9",
                    planned_start_at="2026-08-20T06:00:00Z")
    add_delivery_stop(trip["id"], store["id"], order["id"], 1, "2026-08-20T08:00:00Z",
                      "2026-08-20T09:15:00Z", 120, 100, 600)
    return {"source": source, "target": target, "lent": lent, "held": held,
            "target_tractor": target_tractor, "target_trailer": target_trailer,
            "source_tractor": source_tractor, "trip": trip}


def _borrow(api, ctx, driver_id, tractor_id=None):
    return api.assign_trip_resources(
        ctx["trip"]["id"],
        {"driver_id": driver_id,
         "tractor_id": tractor_id or ctx["target_tractor"]["id"],
         "trailer_id": ctx["target_trailer"]["id"]},
        MANAGER,
    )


def _domicile(api, domicile_id):
    return validate_success(api.get_domicile(domicile_id, PLANNER))


def test_a_terminal_exactly_at_its_target_may_not_borrow(api):
    """PRD §3.5: "Drivers, by contrast, may be borrowed — but only when both terminals agree to
    it arithmetically." And PRD §3.5: "The loan is permitted only when the source's
    `balance_index` is at or above 1.5000 — a terminal sitting exactly at one-and-a-half times
    its headcount target may lend — **and** the target's `balance_index` is strictly below
    1.0000, so a terminal already at exactly its target may not borrow. If either condition
    fails, the assignment is `ERR_DOMICILE_MISMATCH`."

    Design: Corner/validations/the_borrow_gate_needs_a_source_at_1_5000_and_a_target_strictly_under_1_0000
    """
    ctx = _lender_and_borrower()
    assert _domicile(api, ctx["source"]["id"])["balance_index"] == 1.5
    assert _domicile(api, ctx["target"]["id"])["balance_index"] == 1.0

    # The lender is willing; the borrower is not short-handed enough.
    validate_error(
        _borrow(api, ctx, ctx["lent"][0]["id"]),
        ApiErrorId.ERR_DOMICILE_MISMATCH,
        422,
    )
    idle = read_trip(ctx["trip"]["id"])
    assert idle["driver_id"] is None
    assert idle["tractor_id"] is None


def test_equipment_is_never_lent_however_the_indices_stand(api):
    """PRD §3.5: "Equipment domicile is absolute: a tractor's or a trailer's `domicile_id` must
    equal the trip's `domicile_id` outright, and any difference is `ERR_DOMICILE_MISMATCH`."
    And PRD §3.3: "The domicile's `assigned_driver_count` falls by 1 and its `balance_index` is
    recomputed."

    Design: Corner/validations/the_borrow_gate_needs_a_source_at_1_5000_and_a_target_strictly_under_1_0000
    """
    ctx = _lender_and_borrower()
    # A home driver cannot rescue a foreign tractor.
    validate_error(
        _borrow(api, ctx, ctx["held"][0]["id"], tractor_id=ctx["source_tractor"]["id"]),
        ApiErrorId.ERR_DOMICILE_MISMATCH,
        422,
    )
    assert read_tractor(ctx["source_tractor"]["id"])["status"] == "AVAILABLE"

    # One departure drops the target below its target headcount and opens the loan.
    gone = validate_success(
        api.terminate_driver(ctx["held"][2]["id"], {"termination_reason": "VOLUNTARY"},
                             MANAGER)
    )
    assert gone["status"] == "TERMINATED"
    borrower = _domicile(api, ctx["target"]["id"])
    assert borrower["assigned_driver_count"] == 2
    assert borrower["balance_index"] == 0.6667

    crewed = validate_success(_borrow(api, ctx, ctx["lent"][0]["id"]))
    assert crewed["driver_id"] == ctx["lent"][0]["id"]
    assert crewed["tractor_id"] == ctx["target_tractor"]["id"]
    # Lending nobody away, the source's own index is unchanged.
    assert _domicile(api, ctx["source"]["id"])["balance_index"] == 1.5
