"""Requests that violate two rules at once, where only the higher rule may answer."""

from test_helpers import (
    MAINTENANCE,
    MANAGER,
    PLANNER,
    ApiErrorId,
    api_client,
    add_delivery_stop,
    add_other_stop,
    assign_resources,
    get_success_data,
    make_maintenance_coordinator_headers,
    new_domicile,
    new_driver,
    new_order,
    new_pay_plan,
    new_store,
    new_tractor,
    new_trailer,
    new_trip,
    new_work_order,
    plan_trip,
    read_trip,
    set_clock,
    validate_error,
)

UNCREATED_TRIP_ID = "11111111-2222-4333-8444-555555555555"


def _duty_and_rest_conflict():
    """One planned trip, then two candidate trips 300 minutes behind its end.

    Both candidates violate the ten-hour rest gap; only the first also busts the
    fourteen-hour daily duty ceiling, and by exactly one minute.
    """
    set_clock()
    store = new_store(store_code="S-1004", region_code="WEST", dock_count=3,
                      cases_per_hour_unload_rate=600, dock_open_minute=0,
                      dock_close_minute=1439)
    domicile = new_domicile(domicile_code="DOM-PHX", region_code="WEST", tractor_capacity=25,
                            driver_headcount_target=12, fixed_ownership_cents_per_day=11000,
                            overhead_cents_per_day=3500, dedicated_rate_cents_per_mile=280,
                            dedicated_rate_cents_per_case=205)
    pay_plan = new_pay_plan(plan_code="MILE-A", mileage_cents_per_mile=78,
                            stop_cents_per_stop=2200, drop_hook_cents=1500,
                            hourly_cents_per_minute=42, minimum_daily_cents=24000,
                            backhaul_bonus_pct=0.05)
    driver = new_driver(domicile["id"], pay_plan["id"], driver_code="D-77",
                        seniority_date="2019-03-04")
    first_tractor = new_tractor(domicile["id"], unit_code="TR-501", odometer_miles=40000,
                                pm_interval_miles=25000, pm_last_service_odometer=39000)
    spare_tractor = new_tractor(domicile["id"], unit_code="TR-502", odometer_miles=41000,
                                pm_interval_miles=25000, pm_last_service_odometer=40000)
    first_trailer = new_trailer(domicile["id"], trailer_code="VAN-900", capacity_cases=3200)
    spare_trailer = new_trailer(domicile["id"], trailer_code="VAN-901", capacity_cases=3200)

    def order(cases, weight, window_start, window_end):
        return new_order(store["id"], cases=cases, weight_lbs=weight,
                         requested_window_start=window_start,
                         requested_window_end=window_end,
                         temperature_mode="DRY", priority=3)

    def three_stop_trip(code, start, first_cases, first_order, second_order, day_two):
        trip = new_trip(domicile["id"], trip_code=code, planned_start_at=start)
        stop = add_delivery_stop(trip["id"], store["id"], first_order["id"], 1,
                                 "2026-08-05T01:00:00Z" if not day_two else "2026-08-05T19:00:00Z",
                                 "2026-08-05T04:00:00Z" if not day_two else "2026-08-05T22:00:00Z",
                                 240, 240, first_cases)
        add_delivery_stop(trip["id"], store["id"], second_order["id"], 2,
                          "2026-08-05T09:00:00Z" if not day_two else "2026-08-06T01:00:00Z",
                          "2026-08-05T12:00:00Z" if not day_two else "2026-08-06T04:00:00Z",
                          200, 200, 1550)
        add_other_stop(trip["id"], "DROP_OFF", 3,
                       "2026-08-05T13:00:00Z" if not day_two else "2026-08-06T05:00:00Z",
                       "2026-08-05T13:30:00Z" if not day_two else "2026-08-06T05:30:00Z",
                       40, 40, True, cases=0)
        return trip, stop

    committed, _ = three_stop_trip(
        "TRIP-A", "2026-08-05T00:00:00Z", 1550,
        order(1550, 34000, "2026-08-05T00:00:00Z", "2026-08-05T05:00:00Z"),
        order(1550, 34000, "2026-08-05T08:00:00Z", "2026-08-05T13:00:00Z"),
        False,
    )
    staffed = assign_resources(committed["id"], driver["id"], first_tractor["id"],
                               first_trailer["id"])
    planned = plan_trip(committed["id"])

    over_duty, over_duty_stop = three_stop_trip(
        "TRIP-B", "2026-08-05T18:30:00Z", 1556,
        order(1556, 34100, "2026-08-05T18:00:00Z", "2026-08-05T23:00:00Z"),
        order(1550, 34000, "2026-08-06T00:00:00Z", "2026-08-06T05:00:00Z"),
        True,
    )
    at_duty_ceiling, _ = three_stop_trip(
        "TRIP-C", "2026-08-05T18:30:00Z", 1550,
        order(1550, 34000, "2026-08-05T18:00:00Z", "2026-08-05T23:00:00Z"),
        order(1550, 34000, "2026-08-06T00:00:00Z", "2026-08-06T05:00:00Z"),
        True,
    )
    return {
        "driver": driver,
        "spare_tractor": spare_tractor,
        "spare_trailer": spare_trailer,
        "staffed": staffed,
        "planned": planned,
        "over_duty": over_duty,
        "over_duty_stop": over_duty_stop,
        "at_duty_ceiling": at_duty_ceiling,
    }


def _assign_spare(ctx, trip_id):
    """Offer the same driver and the spare rig to a trip that must be refused."""
    return api_client.assign_trip_resources(
        trip_id,
        {
            "driver_id": ctx["driver"]["id"],
            "tractor_id": ctx["spare_tractor"]["id"],
            "trailer_id": ctx["spare_trailer"]["id"],
        },
        MANAGER,
    )


def test_the_duty_ceiling_is_inclusive_so_exactly_fourteen_hours_still_commits(api):
    """PRD §3.5: "All three comparisons are strict: a projection landing exactly on a
    ceiling is feasible."

    Design: Difficulty/priority_pair_validation_conflict/hos_duty_limit_beats_driver_rest_gap_when_both_are_violated
    """
    ctx = _duty_and_rest_conflict()
    assert ctx["staffed"]["planned_duty_minutes"] == 840
    assert ctx["staffed"]["planned_break_minutes"] == 0
    assert ctx["staffed"]["peak_case_load"] == 3100
    assert ctx["planned"]["plan_status"] == "PLANNED"

    over = read_trip(ctx["over_duty"]["id"])
    assert get_success_data(api.get_trip_stop(ctx["over_duty_stop"]["id"], PLANNER))["service_minutes"] == 171
    assert over["planned_service_minutes"] == 361
    assert over["planned_duty_minutes"] == 841
    assert read_trip(ctx["at_duty_ceiling"]["id"])["planned_duty_minutes"] == 840


def test_hours_of_service_answers_first_when_the_rest_gap_is_equally_violated(api):
    """PRD §2.7: "This level outranks the rest-gap check at level 14: a driver who both
    blows the daily duty ceiling and has only ten hours' worth of shortfall in rest since a
    previous trip reports the hours-of-service code, not the rest-gap code."

    Design: Difficulty/priority_pair_validation_conflict/hos_duty_limit_beats_driver_rest_gap_when_both_are_violated
    """
    ctx = _duty_and_rest_conflict()
    validate_error(
        _assign_spare(ctx, ctx["over_duty"]["id"]),
        ApiErrorId.ERR_HOS_DUTY_LIMIT,
        422,
    )
    assert read_trip(ctx["over_duty"]["id"])["driver_id"] is None


def test_removing_one_duty_minute_surfaces_the_rest_gap_from_the_same_call(api):
    """PRD §3.5: "A gap of fewer than ten hours is refused with `ERR_DRIVER_REST_GAP`. The
    comparison is strict, so a gap of exactly ten hours is legal and one minute less is
    not."

    Design: Difficulty/priority_pair_validation_conflict/hos_duty_limit_beats_driver_rest_gap_when_both_are_violated
    """
    ctx = _duty_and_rest_conflict()
    validate_error(
        _assign_spare(ctx, ctx["at_duty_ceiling"]["id"]),
        ApiErrorId.ERR_DRIVER_REST_GAP,
        422,
    )
    assert read_trip(ctx["at_duty_ceiling"]["id"])["driver_id"] is None


def _twice_deferred_work_order():
    """A manually booked shop window pushed back the maximum two times.

    No trip ever references the tractor, so the maintenance-conflict geometry has
    nothing to complain about and only the state and ceiling rules can answer.
    """
    set_clock()
    domicile = new_domicile(domicile_code="DOM-CHI", region_code="MIDWEST", tractor_capacity=40,
                            driver_headcount_target=20, fixed_ownership_cents_per_day=12000,
                            overhead_cents_per_day=4000, dedicated_rate_cents_per_mile=285,
                            dedicated_rate_cents_per_case=210)
    tractor = new_tractor(domicile["id"], unit_code="TR-501", odometer_miles=40000,
                          pm_interval_miles=25000, pm_last_service_odometer=39000)
    order = new_work_order(asset_kind="TRACTOR", tractor_id=tractor["id"], service_type="PM_B",
                           window_start_at="2026-08-10T06:00:00Z",
                           window_end_at="2026-08-10T14:00:00Z")
    assert order["status"] == "SCHEDULED"
    assert order["deferral_count"] == 0
    assert order["auto_generated"] is False

    first = get_success_data(
        api_client.defer_work_order(order["id"], {"reason_code": "PARTS_BACKORDER"}, MAINTENANCE)
    )
    get_success_data(
        api_client.reschedule_work_order(
            order["id"],
            {"window_start_at": "2026-08-11T06:00:00Z", "window_end_at": "2026-08-11T14:00:00Z"},
            MAINTENANCE,
        )
    )
    second = get_success_data(
        api_client.defer_work_order(order["id"], {"reason_code": "BAY_FULL"}, MAINTENANCE)
    )
    return {"tractor": tractor, "order": order, "first": first, "second": second}


def test_a_deferred_order_at_the_ceiling_reports_its_state_not_its_ceiling(api):
    """PRD §2.7: "This level outranks every capacity and constraint check at level 15 —
    deferring a work order that is *already* `DEFERRED` and whose deferral count has
    reached its ceiling reports `ERR_INVALID_STATE_TRANSITION`, never
    `ERR_DEFERRAL_LIMIT`."

    Design: Difficulty/priority_pair_validation_conflict/own_state_check_beats_deferral_limit_on_an_already_deferred_work_order
    """
    ctx = _twice_deferred_work_order()
    assert ctx["first"]["deferral_count"] == 1
    assert ctx["second"]["deferral_count"] == 2
    assert ctx["second"]["status"] == "DEFERRED"

    validate_error(
        api.defer_work_order(ctx["order"]["id"], {"reason_code": "ONE_MORE_WEEK"}, MAINTENANCE),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        409,
    )
    unmoved = get_success_data(api.get_work_order(ctx["order"]["id"], MAINTENANCE))
    assert unmoved["status"] == "DEFERRED"
    assert unmoved["deferral_count"] == 2


def test_returning_the_order_to_scheduled_exposes_the_deferral_ceiling(api):
    """PRD §3.7: "Deferral takes a work order `SCHEDULED → DEFERRED`, raising
    `deferral_count` by 1, and is allowed only while `deferral_count` is below 2 — a third
    attempt is `ERR_DEFERRAL_LIMIT`."

    Design: Difficulty/priority_pair_validation_conflict/own_state_check_beats_deferral_limit_on_an_already_deferred_work_order
    """
    ctx = _twice_deferred_work_order()
    rescheduled = get_success_data(
        api.reschedule_work_order(
            ctx["order"]["id"],
            {"window_start_at": "2026-08-12T06:00:00Z", "window_end_at": "2026-08-12T14:00:00Z"},
            MAINTENANCE,
        )
    )
    assert rescheduled["status"] == "SCHEDULED"
    # Rescheduling moves the window and nothing else; the spent deferrals stay spent.
    assert rescheduled["deferral_count"] == 2

    validate_error(
        api.defer_work_order(ctx["order"]["id"], {"reason_code": "ONE_MORE_WEEK"}, MAINTENANCE),
        ApiErrorId.ERR_DEFERRAL_LIMIT,
        409,
    )
    final = get_success_data(api.get_work_order(ctx["order"]["id"], MAINTENANCE))
    assert final["status"] == "SCHEDULED"
    assert final["deferral_count"] == 2
    assert final["window_start_at"].startswith("2026-08-12T06:00:00")


def test_a_forbidden_role_cannot_learn_whether_a_trip_exists(api):
    """PRD §2.7: "This deliberately outranks existence, so a forbidden role probing a
    random UUID receives 403 and never 404."

    Design: Difficulty/priority_pair_validation_conflict/role_check_beats_existence_so_a_forbidden_role_cannot_probe_for_404
    """
    set_clock()
    validate_error(
        api.plan_trip(UNCREATED_TRIP_ID, make_maintenance_coordinator_headers("user-mc-7")),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )


def test_the_authorised_role_sees_the_missing_trip_the_forbidden_role_could_not(api):
    """PRD §2.7: "The row named by the final path parameter must exist."

    Design: Difficulty/priority_pair_validation_conflict/role_check_beats_existence_so_a_forbidden_role_cannot_probe_for_404
    """
    set_clock()
    validate_error(
        api.plan_trip(UNCREATED_TRIP_ID, PLANNER),
        ApiErrorId.ERR_TRIP_NOT_FOUND,
        404,
    )
