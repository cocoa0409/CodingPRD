"""Three shared resources, three different interval geometries, probed on the edge."""

from test_helpers import (
    MAINTENANCE,
    MANAGER,
    PLANNER,
    ApiErrorId,
    add_delivery_stop,
    api_client,
    assign_resources,
    create_work_order_payload,
    get_success_data,
    new_domicile,
    new_driver,
    new_order,
    new_pay_plan,
    new_store,
    new_tractor,
    new_trailer,
    new_trip,
    plan_trip,
    read_store,
    read_trip,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

MILE_A = {
    "plan_code": "MILE-A",
    "mileage_cents_per_mile": 78,
    "stop_cents_per_stop": 2200,
    "drop_hook_cents": 1500,
    "hourly_cents_per_minute": 42,
    "minimum_daily_cents": 24000,
    "backhaul_bonus_pct": 0.05,
}


def _one_door_store_with_three_staffed_trips():
    """A single-door store and three identical trips at 08:00, 09:00 and 10:00.

    Each trip has its own driver and its own rig, so nothing but the dock interval
    can separate them, and all three are staffed while every trip is still DRAFT.
    """
    set_clock()
    store = new_store(store_code="S-1009", region_code="WEST", dock_count=1,
                      cases_per_hour_unload_rate=600, dock_open_minute=0,
                      dock_close_minute=1439)
    domicile = new_domicile(domicile_code="DOM-LAX", region_code="WEST", tractor_capacity=35,
                            driver_headcount_target=18, fixed_ownership_cents_per_day=13000,
                            overhead_cents_per_day=4200, dedicated_rate_cents_per_mile=290,
                            dedicated_rate_cents_per_case=215)
    pay_plan = new_pay_plan(**MILE_A)
    trips = []
    for index, (code, start, arrival, departure) in enumerate(
        [
            ("TRIP-1", "06:00", "08:00", "10:00"),
            ("TRIP-2", "07:00", "09:00", "11:00"),
            ("TRIP-3", "08:00", "10:00", "12:00"),
        ]
    ):
        driver = new_driver(domicile["id"], pay_plan["id"], driver_code="D-9%d" % (6 + index),
                           seniority_date="2014-0%d-06" % (index + 1))
        tractor = new_tractor(domicile["id"], unit_code="TR-54%d" % (index + 1),
                              odometer_miles=20000, pm_interval_miles=25000,
                              pm_last_service_odometer=19000)
        trailer = new_trailer(domicile["id"], trailer_code="VAN-94%d" % (index + 1),
                              capacity_cases=1800)
        order = new_order(store["id"], cases=600, weight_lbs=13000,
                          requested_window_start="2026-08-10T00:00:00Z",
                          requested_window_end="2026-08-10T23:00:00Z",
                          temperature_mode="DRY", priority=3)
        trip = new_trip(domicile["id"], trip_code=code,
                        planned_start_at="2026-08-10T%s:00Z" % start)
        stop = add_delivery_stop(trip["id"], store["id"], order["id"], 1,
                                 "2026-08-10T%s:00Z" % arrival,
                                 "2026-08-10T%s:00Z" % departure, 120, 120, 600)
        staffed = assign_resources(trip["id"], driver["id"], tractor["id"], trailer["id"])
        trips.append({"trip": trip, "stop": stop, "staffed": staffed})
    return {"store": store, "trips": trips}


def test_the_single_door_admits_one_occupant_and_refuses_the_overlapper(api):
    """PRD §3.5: "If the number of such existing occupants plus the candidate itself would
    exceed the store's `dock_count`, the commitment is refused with
    `ERR_DOCK_CAPACITY_EXCEEDED`; equivalently, reject as soon as the already-committed
    overlapping stops have reached the door count."

    Design: Difficulty/resource_temporal_overlap/store_dock_tolerates_overlap_up_to_the_door_count_and_ignores_adjacency
    """
    ctx = _one_door_store_with_three_staffed_trips()
    assert ctx["store"]["dock_count"] == 1
    assert ctx["trips"][0]["stop"]["status"] == "PLANNED"
    # The three trips are identical in every respect except their dock interval.
    assert [entry["staffed"]["planned_duty_minutes"] for entry in ctx["trips"]] == [195, 195, 195]

    assert plan_trip(ctx["trips"][0]["trip"]["id"])["plan_status"] == "PLANNED"
    validate_error(
        api.plan_trip(ctx["trips"][1]["trip"]["id"], PLANNER),
        ApiErrorId.ERR_DOCK_CAPACITY_EXCEEDED,
        409,
    )
    assert read_trip(ctx["trips"][1]["trip"]["id"])["plan_status"] == "DRAFT"


def test_an_adjacent_occupation_leaves_the_door_free_and_draft_trips_reserve_nothing(api):
    """PRD §2.9: "A delivery stop occupies its store's dock from `scheduled_arrival_at`
    inclusive up to `scheduled_departure_at` exclusive. Two stops whose windows merely touch
    — one departing at precisely the instant the next arrives — do **not** collide."

    Design: Difficulty/resource_temporal_overlap/store_dock_tolerates_overlap_up_to_the_door_count_and_ignores_adjacency
    """
    ctx = _one_door_store_with_three_staffed_trips()
    plan_trip(ctx["trips"][0]["trip"]["id"])
    validate_error(
        api.plan_trip(ctx["trips"][1]["trip"]["id"], PLANNER),
        ApiErrorId.ERR_DOCK_CAPACITY_EXCEEDED,
        409,
    )
    # 10:00 is not strictly later than 10:00, and the refused trip is still DRAFT.
    assert plan_trip(ctx["trips"][2]["trip"]["id"])["plan_status"] == "PLANNED"
    assert read_store(ctx["store"]["id"])["open_scheduled_cases"] == 1200


def _planned_trip_holding_one_tractor():
    """TRIP-S runs 07:00 to 14:50, so TR-521 is reserved from 05:00 through 16:50."""
    set_clock()
    store = new_store(store_code="S-1010", region_code="MIDWEST", dock_count=2,
                      cases_per_hour_unload_rate=600, dock_open_minute=0,
                      dock_close_minute=1439)
    domicile = new_domicile(domicile_code="DOM-IND", region_code="MIDWEST", tractor_capacity=24,
                            driver_headcount_target=12, fixed_ownership_cents_per_day=11500,
                            overhead_cents_per_day=3600, dedicated_rate_cents_per_mile=282,
                            dedicated_rate_cents_per_case=206)
    pay_plan = new_pay_plan(**MILE_A)
    driver = new_driver(domicile["id"], pay_plan["id"], driver_code="D-99",
                       seniority_date="2013-07-01")
    tractor = new_tractor(domicile["id"], unit_code="TR-521", odometer_miles=50000,
                          pm_interval_miles=25000, pm_last_service_odometer=49000)
    trailer = new_trailer(domicile["id"], trailer_code="VAN-921", capacity_cases=1800)
    order = new_order(store["id"], cases=900, weight_lbs=19500,
                      requested_window_start="2026-08-03T08:00:00Z",
                      requested_window_end="2026-08-03T15:00:00Z",
                      temperature_mode="DRY", priority=3)
    trip = new_trip(domicile["id"], trip_code="TRIP-S",
                    planned_start_at="2026-08-03T07:00:00Z")
    stop = add_delivery_stop(trip["id"], store["id"], order["id"], 1,
                             "2026-08-03T09:00:00Z", "2026-08-03T14:50:00Z", 120, 120, 900)
    staffed = assign_resources(trip["id"], driver["id"], tractor["id"], trailer["id"])
    return {
        "tractor": tractor,
        "trailer": trailer,
        "stop": stop,
        "staffed": staffed,
        "planned": plan_trip(trip["id"]),
    }


def _shop_probe(tractor_id, service_type, window_start_at, window_end_at):
    return api_client.create_work_order(
        create_work_order_payload(asset_kind="TRACTOR", tractor_id=tractor_id,
                                  service_type=service_type,
                                  window_start_at=window_start_at,
                                  window_end_at=window_end_at),
        MAINTENANCE,
    )


def test_a_shop_window_touching_the_right_edge_of_the_buffer_collides(api):
    """PRD §2.9: "Because both edges are inclusive, merely touching intervals **do**
    collide: a shop window starting at exactly the instant two hours after a trip's planned
    end is rejected, while one starting a single minute later is accepted."

    Design: Difficulty/resource_temporal_overlap/tractor_shop_window_collides_on_touch_across_a_120_minute_buffer
    """
    ctx = _planned_trip_holding_one_tractor()
    assert ctx["stop"]["service_minutes"] == 105
    assert ctx["staffed"]["planned_duty_minutes"] == 225
    assert ctx["staffed"]["planned_end_at"].startswith("2026-08-03T14:50:00")
    assert ctx["planned"]["plan_status"] == "PLANNED"

    validate_error(
        _shop_probe(ctx["tractor"]["id"], "PM_A",
                    "2026-08-03T16:50:00Z", "2026-08-03T20:50:00Z"),
        ApiErrorId.ERR_ASSET_MAINTENANCE_CONFLICT,
        409,
    )
    admitted = validate_success(
        _shop_probe(ctx["tractor"]["id"], "PM_A",
                    "2026-08-03T16:51:00Z", "2026-08-03T20:51:00Z"),
        201,
    )
    assert admitted["status"] == "SCHEDULED"


def test_the_left_edge_of_the_buffer_mirrors_the_right_and_refusals_write_nothing(api):
    """PRD §3.5: "the trip's occupation runs from two hours before its `planned_start_at`
    through two hours after its `planned_end_at`, both edges inclusive, and it is compared
    against every work order of that same asset whose status is `SCHEDULED`, `DEFERRED` or
    `IN_SHOP`; `COMPLETED` and `CANCELLED` orders are ignored entirely."

    Design: Difficulty/resource_temporal_overlap/tractor_shop_window_collides_on_touch_across_a_120_minute_buffer
    """
    ctx = _planned_trip_holding_one_tractor()
    validate_success(
        _shop_probe(ctx["tractor"]["id"], "PM_A",
                    "2026-08-03T16:51:00Z", "2026-08-03T20:51:00Z"),
        201,
    )
    validate_error(
        _shop_probe(ctx["tractor"]["id"], "INSPECTION",
                    "2026-08-03T01:00:00Z", "2026-08-03T05:00:00Z"),
        ApiErrorId.ERR_ASSET_MAINTENANCE_CONFLICT,
        409,
    )
    early = validate_success(
        _shop_probe(ctx["tractor"]["id"], "INSPECTION",
                    "2026-08-02T23:00:00Z", "2026-08-03T04:59:00Z"),
        201,
    )
    assert early["status"] == "SCHEDULED"

    rows, meta = validate_paginated(
        api.list_work_orders(MAINTENANCE, {"tractor_id": ctx["tractor"]["id"]})
    )
    assert meta["total_count"] == 2
    assert all(row["asset_kind"] == "TRACTOR" for row in rows)
    # The buffer is evaluated per asset, so the trailer of the same trip is untouched.
    _, trailer_meta = validate_paginated(
        api.list_work_orders(MAINTENANCE, {"trailer_id": ctx["trailer"]["id"]})
    )
    assert trailer_meta["total_count"] == 0


def _driver_with_one_committed_trip():
    """TRIP-T ends 2026-08-04T14:50Z; TRIP-U starts 599 minutes later, TRIP-V 600."""
    set_clock()
    store = new_store(store_code="S-1011", region_code="EAST", dock_count=2,
                      cases_per_hour_unload_rate=600, dock_open_minute=0,
                      dock_close_minute=1439)
    domicile = new_domicile(domicile_code="DOM-PHL", region_code="EAST", tractor_capacity=20,
                            driver_headcount_target=10, fixed_ownership_cents_per_day=12500,
                            overhead_cents_per_day=3900, dedicated_rate_cents_per_mile=288,
                            dedicated_rate_cents_per_case=212)
    pay_plan = new_pay_plan(**MILE_A)
    driver = new_driver(domicile["id"], pay_plan["id"], driver_code="D-100",
                       seniority_date="2012-11-11")
    held_tractor = new_tractor(domicile["id"], unit_code="TR-531", odometer_miles=60000,
                               pm_interval_miles=25000, pm_last_service_odometer=59000)
    free_tractor = new_tractor(domicile["id"], unit_code="TR-532", odometer_miles=60000,
                               pm_interval_miles=25000, pm_last_service_odometer=59000)
    held_trailer = new_trailer(domicile["id"], trailer_code="VAN-931", capacity_cases=1800)
    free_trailer = new_trailer(domicile["id"], trailer_code="VAN-932", capacity_cases=1800)

    first_order = new_order(store["id"], cases=900, weight_lbs=19500,
                            requested_window_start="2026-08-04T08:00:00Z",
                            requested_window_end="2026-08-04T15:00:00Z",
                            temperature_mode="DRY", priority=3)
    committed = new_trip(domicile["id"], trip_code="TRIP-T",
                         planned_start_at="2026-08-04T06:00:00Z")
    add_delivery_stop(committed["id"], store["id"], first_order["id"], 1,
                      "2026-08-04T08:00:00Z", "2026-08-04T14:50:00Z", 120, 120, 900)
    staffed = assign_resources(committed["id"], driver["id"], held_tractor["id"],
                               held_trailer["id"])
    planned = plan_trip(committed["id"])

    def short_trip(code, start, arrival, departure):
        order = new_order(store["id"], cases=300, weight_lbs=6500,
                          requested_window_start="2026-08-05T00:00:00Z",
                          requested_window_end="2026-08-05T06:00:00Z",
                          temperature_mode="DRY", priority=3)
        trip = new_trip(domicile["id"], trip_code=code, planned_start_at=start)
        add_delivery_stop(trip["id"], store["id"], order["id"], 1, arrival, departure,
                          60, 60, 300)
        return trip

    return {
        "driver": driver,
        "free_tractor": free_tractor,
        "free_trailer": free_trailer,
        "staffed": staffed,
        "planned": planned,
        "too_soon": short_trip("TRIP-U", "2026-08-05T00:49:00Z",
                               "2026-08-05T02:00:00Z", "2026-08-05T03:00:00Z"),
        "just_legal": short_trip("TRIP-V", "2026-08-05T00:50:00Z",
                                 "2026-08-05T04:00:00Z", "2026-08-05T05:00:00Z"),
    }


def _staff_with_the_free_rig(ctx, trip_id):
    return api_client.assign_trip_resources(
        trip_id,
        {
            "driver_id": ctx["driver"]["id"],
            "tractor_id": ctx["free_tractor"]["id"],
            "trailer_id": ctx["free_trailer"]["id"],
        },
        MANAGER,
    )


def test_a_gap_of_599_minutes_is_refused_although_the_duty_periods_are_disjoint(api):
    """PRD §3.5: "For each such trip, if the candidate trip's `planned_start_at` is at or
    after the other trip's `planned_end_at`, the gap is the number of minutes between them;
    if instead the other trip's `planned_start_at` is at or after the candidate trip's
    `planned_end_at`, the gap is the number of minutes in that direction; and if neither
    holds — the two duty periods overlap outright — the gap is zero."

    Design: Difficulty/resource_temporal_overlap/driver_needs_600_minutes_of_separation_not_merely_disjoint_duty
    """
    ctx = _driver_with_one_committed_trip()
    assert ctx["driver"]["drive_minutes_used_today"] == 0
    assert ctx["driver"]["duty_minutes_used_today"] == 0
    assert ctx["staffed"]["planned_end_at"].startswith("2026-08-04T14:50:00")
    assert ctx["planned"]["plan_status"] == "PLANNED"

    validate_error(
        _staff_with_the_free_rig(ctx, ctx["too_soon"]["id"]),
        ApiErrorId.ERR_DRIVER_REST_GAP,
        422,
    )
    refused = read_trip(ctx["too_soon"]["id"])
    assert refused["driver_id"] is None
    assert refused["plan_status"] == "DRAFT"


def test_a_gap_of_exactly_600_minutes_is_legal_and_takes_the_free_rig(api):
    """PRD §3.5: "A gap of fewer than ten hours is refused with `ERR_DRIVER_REST_GAP`. The
    comparison is strict, so a gap of exactly ten hours is legal and one minute less is
    not."

    Design: Difficulty/resource_temporal_overlap/driver_needs_600_minutes_of_separation_not_merely_disjoint_duty
    """
    ctx = _driver_with_one_committed_trip()
    validate_error(
        _staff_with_the_free_rig(ctx, ctx["too_soon"]["id"]),
        ApiErrorId.ERR_DRIVER_REST_GAP,
        422,
    )
    staffed = get_success_data(_staff_with_the_free_rig(ctx, ctx["just_legal"]["id"]))
    assert staffed["driver_id"] == ctx["driver"]["id"]
    assert staffed["planned_duty_minutes"] == 105
    assert get_success_data(api.get_tractor(ctx["free_tractor"]["id"], MAINTENANCE))["status"] == "ASSIGNED"
