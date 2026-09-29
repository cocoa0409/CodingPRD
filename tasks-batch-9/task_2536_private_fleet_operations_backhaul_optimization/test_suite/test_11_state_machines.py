"""Declared state machines: initial states, valid transitions, refusals and lockdown."""

from test_helpers import (
    MAINTENANCE,
    MANAGER,
    PLANNER,
    SAFETY,
    ApiErrorId,
    add_delivery_stop,
    add_other_stop,
    api_client,
    assert_route_bid,
    assert_route_posting,
    assign_resources,
    dispatch_trip,
    get_success_data,
    make_driver_headers,
    make_safety_manager_headers,
    make_transport_manager_headers,
    new_domicile,
    new_driver,
    new_order,
    new_pay_plan,
    new_route_posting,
    new_telematics_event,
    new_tractor,
    new_trailer,
    new_trip,
    new_work_order,
    place_bid,
    plan_trip,
    read_driver,
    read_posting,
    read_store,
    read_trip,
    set_clock,
    setup_base_fleet,
    validate_error,
    validate_success,
)

PUBLISHER = make_transport_manager_headers("user-tm-1")
AWARDER = make_transport_manager_headers("user-tm-2")
COACH = make_safety_manager_headers("user-safety-1")


def _staffed_draft_trip():
    """One delivery stop, a full crew, and no plan call — the trip is still DRAFT."""
    ctx = setup_base_fleet("s1")
    trip = new_trip(ctx["domicile"]["id"], trip_code="TRIP-SM1",
                    planned_start_at="2026-08-20T06:00:00Z")
    stop = add_delivery_stop(trip["id"], ctx["store"]["id"], ctx["order"]["id"], 1,
                             "2026-08-20T08:00:00Z", "2026-08-20T09:15:00Z", 120, 100, 600)
    staffed = assign_resources(trip["id"], ctx["driver"]["id"], ctx["tractor"]["id"],
                               ctx["trailer"]["id"])
    return {"trip": trip, "stop": stop, "staffed": staffed}


def test_a_fully_crewed_draft_trip_may_not_skip_the_plan_step(api):
    """PRD §3.7: "Dispatch is a `TransportManager` act taking the trip `PLANNED →
    DISPATCHED`. Any other starting `plan_status` is `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/trip_dispatch_from_draft_is_rejected
    """
    ctx = _staffed_draft_trip()
    assert ctx["stop"]["service_minutes"] == 75
    # Crewing fills three references; it is not a transition on the operations dimension.
    assert ctx["staffed"]["plan_status"] == "DRAFT"
    assert ctx["staffed"]["driver_id"] is not None

    validate_error(
        api.dispatch_trip(ctx["trip"]["id"], MANAGER),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        409,
    )
    assert read_trip(ctx["trip"]["id"])["plan_status"] == "DRAFT"


def _posting_published_by_user_tm_1(suffix, **overrides):
    ctx = setup_base_fleet(suffix, driver_overrides={"seniority_date": "2018-06-15"})
    posting = new_route_posting(ctx["domicile"]["id"], PUBLISHER, **overrides)
    return ctx, posting


def test_a_published_posting_opens_with_no_winner_and_no_bids(api):
    """PRD §3.9: "Its `status` runs `OPEN`, then either `AWARDED` or `VACANT` or
    `CANCELLED`; `awarded_driver_id` starts null; `bid_count` starts at zero; and
    `created_by_user_id` records who published it, because that identity is later checked
    against whoever awards it."

    Design: Corner/state_machines/route_posting_and_bid_start_in_their_declared_initial_states
    """
    _, posting = _posting_published_by_user_tm_1(
        "s2", route_code="RT-SM2", weekly_miles=2100, weekly_stops=18,
        start_effective_date="2026-09-07", bid_close_at="2026-08-10T00:00:00Z",
    )
    assert_route_posting(posting)
    assert posting["status"] == "OPEN"
    assert posting["awarded_driver_id"] is None
    assert posting["bid_count"] == 0
    assert posting["version"] == 1
    assert posting["created_by_user_id"] == "user-tm-1"
    assert posting["weekly_miles"] == 2100
    assert posting["weekly_stops"] == 18


def test_the_first_bid_is_born_submitted_and_moves_its_parent_board(api):
    """PRD §3.9: "Each accepted bid records `seniority_date_snapshot` and
    `safety_score_snapshot`, copies of the driver's `seniority_date` and `safety_score` as
    they stood at bid time, kept for audit only. Its `status` starts at `SUBMITTED` and may
    become `AWARDED`, `PASSED_OVER` or `WITHDRAWN`. Creation raises the posting's
    `bid_count` by one and its `version` by one."

    Design: Corner/state_machines/route_posting_and_bid_start_in_their_declared_initial_states
    """
    ctx, posting = _posting_published_by_user_tm_1(
        "s2", route_code="RT-SM2", weekly_miles=2100, weekly_stops=18,
        start_effective_date="2026-09-07", bid_close_at="2026-08-10T00:00:00Z",
    )
    bid = place_bid(ctx["driver"]["id"], posting["id"], posting["version"])
    assert_route_bid(bid)
    assert bid["status"] == "SUBMITTED"
    assert bid["driver_id"] == ctx["driver"]["id"]
    assert bid["route_posting_id"] == posting["id"]
    assert bid["seniority_date_snapshot"].startswith("2018-06-15")
    assert bid["safety_score_snapshot"] == 100
    assert bid["version"] == 1

    reread = read_posting(posting["id"])
    assert reread["bid_count"] == 1
    assert reread["version"] == 2
    assert reread["status"] == "OPEN"


def _trip_cancelled_from_draft():
    """A staffed, stopped trip taken straight from DRAFT to CANCELLED."""
    ctx = setup_base_fleet("s3")
    trip = new_trip(ctx["domicile"]["id"], trip_code="TRIP-SM3",
                    planned_start_at="2026-08-20T06:00:00Z")
    stop = add_delivery_stop(trip["id"], ctx["store"]["id"], ctx["order"]["id"], 1,
                             "2026-08-20T08:00:00Z", "2026-08-20T09:15:00Z", 120, 100, 600)
    assign_resources(trip["id"], ctx["driver"]["id"], ctx["tractor"]["id"],
                     ctx["trailer"]["id"])
    cancelled = get_success_data(
        api_client.cancel_trip(trip["id"], {"reason_code": "STORE_CLOSURE"}, PLANNER)
    )
    return {"ctx": ctx, "trip": trip, "stop": stop, "cancelled": cancelled}


def test_cancelling_from_draft_skips_the_stop_and_leaves_the_ledger_alone(api):
    """PRD §3.7: "From `DRAFT`, cancellation takes the trip `DRAFT → CANCELLED`: every stop
    in `PLANNED` or `ARRIVED` moves to `SKIPPED`; the tractor and trailer, if non-null,
    return to `AVAILABLE`; and the trip's `driver_id`, `tractor_id` and `trailer_id` are all
    cleared to null. No replenishment order is ever `SCHEDULED` while a trip is `DRAFT`, so
    the order and store-ledger links do **not** fire in this shape."

    Design: Corner/state_machines/cancelled_trip_refuses_plan_dispatch_stops_and_a_second_cancel
    """
    ctx = _trip_cancelled_from_draft()
    cancelled = ctx["cancelled"]
    assert cancelled["plan_status"] == "CANCELLED"
    assert cancelled["driver_id"] is None
    assert cancelled["tractor_id"] is None
    assert cancelled["trailer_id"] is None

    assert get_success_data(
        api.get_trip_stop(ctx["stop"]["id"], PLANNER)
    )["status"] == "SKIPPED"
    assert get_success_data(
        api.get_tractor(ctx["ctx"]["tractor"]["id"], MAINTENANCE)
    )["status"] == "AVAILABLE"
    assert get_success_data(
        api.get_order(ctx["ctx"]["order"]["id"], PLANNER)
    )["status"] == "UNSCHEDULED"
    assert read_store(ctx["ctx"]["store"]["id"])["open_scheduled_cases"] == 0


def test_the_cancelled_trip_reports_the_plan_gate_code_for_plan_and_for_appends(api):
    """PRD §3.4: "Stops are then appended one at a time, and only while the trip is still
    `DRAFT` — an append against any later plan status is `ERR_TRIP_NOT_DRAFT`."

    Design: Corner/state_machines/cancelled_trip_refuses_plan_dispatch_stops_and_a_second_cancel
    """
    ctx = _trip_cancelled_from_draft()
    validate_error(
        api.plan_trip(ctx["trip"]["id"], PLANNER),
        ApiErrorId.ERR_TRIP_NOT_DRAFT,
        409,
    )
    validate_error(
        api.add_trip_stop(
            ctx["trip"]["id"],
            {
                "sequence": 2,
                "stop_type": "FUEL",
                "scheduled_arrival_at": "2026-08-20T10:00:00Z",
                "scheduled_departure_at": "2026-08-20T10:25:00Z",
                "drive_minutes_from_prev": 30,
                "miles_from_prev": 20,
                "segment_loaded": False,
            },
            PLANNER,
        ),
        ApiErrorId.ERR_TRIP_NOT_DRAFT,
        409,
    )
    unmoved = read_trip(ctx["trip"]["id"])
    assert unmoved["plan_status"] == "CANCELLED"
    assert unmoved["stop_count"] == 1


def test_dispatch_and_a_second_cancel_report_the_generic_transition_code(api):
    """PRD §3.7: "Cancellation is a `FleetPlanner` or `TransportManager` act; a `COMPLETED`
    or already-`CANCELLED` trip cannot be cancelled again."

    Design: Corner/state_machines/cancelled_trip_refuses_plan_dispatch_stops_and_a_second_cancel
    """
    ctx = _trip_cancelled_from_draft()
    validate_error(
        api.dispatch_trip(ctx["trip"]["id"], MANAGER),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        409,
    )
    validate_error(
        api.cancel_trip(ctx["trip"]["id"], {"reason_code": "STORE_CLOSURE"}, PLANNER),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        409,
    )
    assert read_trip(ctx["trip"]["id"])["plan_status"] == "CANCELLED"


def _posting_with_one_withdrawable_bid():
    ctx = setup_base_fleet("s4", driver_overrides={"seniority_date": "2020-01-20"})
    posting = new_route_posting(ctx["domicile"]["id"], PUBLISHER, route_code="RT-SM4",
                                weekly_miles=1900, weekly_stops=15,
                                start_effective_date="2026-09-07",
                                bid_close_at="2026-08-10T00:00:00Z")
    bid = place_bid(ctx["driver"]["id"], posting["id"], posting["version"])
    return {"ctx": ctx, "posting": posting, "bid": bid}


def test_withdrawing_a_bid_gives_the_seat_back_to_the_board(api):
    """PRD §3.9: "A driver may withdraw their own bid — anyone else's is
    `ERR_DRIVER_SCOPE_VIOLATION` — which moves it `SUBMITTED → WITHDRAWN`, lowers the
    posting's `bid_count` by one, and advances the posting's `version`."

    Design: Corner/state_machines/withdrawing_the_same_route_bid_twice_is_refused
    """
    ctx = _posting_with_one_withdrawable_bid()
    driver_headers = make_driver_headers(ctx["ctx"]["driver"]["id"])
    withdrawn = validate_success(api.withdraw_route_bid(ctx["bid"]["id"], driver_headers))
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["version"] == 2

    board = read_posting(ctx["posting"]["id"])
    # 1 at publication, 2 from the bid, 3 from the withdrawal.
    assert board["bid_count"] == 0
    assert board["version"] == 3
    assert board["status"] == "OPEN"


def test_the_same_withdrawal_twice_is_a_refusal_and_not_a_second_decrement(api):
    """PRD §2.7: "The row's current state must admit the requested transition." And: "The
    general code is `ERR_INVALID_STATE_TRANSITION`, with more specific codes where §3 names
    them."

    Design: Corner/state_machines/withdrawing_the_same_route_bid_twice_is_refused
    """
    ctx = _posting_with_one_withdrawable_bid()
    driver_headers = make_driver_headers(ctx["ctx"]["driver"]["id"])
    validate_success(api.withdraw_route_bid(ctx["bid"]["id"], driver_headers))

    validate_error(
        api.withdraw_route_bid(ctx["bid"]["id"], driver_headers),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        409,
    )
    still = get_success_data(api.get_route_bid(ctx["bid"]["id"], MANAGER))
    assert still["status"] == "WITHDRAWN"
    assert still["version"] == 2
    board = read_posting(ctx["posting"]["id"])
    assert board["bid_count"] == 0
    assert board["version"] == 3


def _tractor_with_an_inspection_and_a_pm_booking():
    """TR-SM5 sits 10000 miles into a 25000-mile interval, with two shop windows booked."""
    set_clock()
    domicile = new_domicile(domicile_code="DOM-SM5", region_code="MIDWEST")
    tractor = new_tractor(domicile["id"], unit_code="TR-SM5", odometer_miles=50000,
                          pm_interval_miles=25000, pm_last_service_odometer=40000)
    inspection = new_work_order(asset_kind="TRACTOR", tractor_id=tractor["id"],
                                service_type="INSPECTION",
                                window_start_at="2026-08-04T08:00:00Z",
                                window_end_at="2026-08-04T12:00:00Z")
    preventive = new_work_order(asset_kind="TRACTOR", tractor_id=tractor["id"],
                                service_type="PM_A",
                                window_start_at="2026-08-06T08:00:00Z",
                                window_end_at="2026-08-06T16:00:00Z")
    return {"tractor": tractor, "inspection": inspection, "preventive": preventive}


def _run_the_shop_visit(work_order_id):
    started = validate_success(api_client.start_work_order(work_order_id, MAINTENANCE))
    finished = validate_success(api_client.complete_work_order(work_order_id, {}, MAINTENANCE))
    return started, finished


def test_an_inspection_takes_the_tractor_through_the_shop_without_rebasing_it(api):
    """PRD §3.2: "Starting the work takes the order `SCHEDULED → IN_SHOP` and drives the
    asset itself `AVAILABLE → IN_SHOP`; if the asset is not `AVAILABLE` at that moment the
    request fails with `ERR_ASSET_NOT_AVAILABLE`."

    Design: Corner/state_machines/pm_work_order_start_and_complete_reset_the_tractor_pm_counters
    """
    ctx = _tractor_with_an_inspection_and_a_pm_booking()
    assert ctx["tractor"]["miles_since_pm"] == 10000
    assert ctx["tractor"]["pm_hold"] is False
    assert ctx["tractor"]["status"] == "AVAILABLE"
    assert ctx["inspection"]["status"] == "SCHEDULED"
    assert ctx["inspection"]["auto_generated"] is False
    assert ctx["inspection"]["deferral_count"] == 0

    started = validate_success(api.start_work_order(ctx["inspection"]["id"], MAINTENANCE))
    assert started["status"] == "IN_SHOP"
    assert get_success_data(
        api.get_tractor(ctx["tractor"]["id"], MAINTENANCE)
    )["status"] == "IN_SHOP"

    finished = validate_success(api.complete_work_order(ctx["inspection"]["id"], {}, MAINTENANCE))
    assert finished["status"] == "COMPLETED"
    after = get_success_data(api.get_tractor(ctx["tractor"]["id"], MAINTENANCE))
    assert after["status"] == "AVAILABLE"
    # An INSPECTION is not one of the two preventive classes, so no baseline moves.
    assert after["miles_since_pm"] == 10000
    assert after["pm_last_service_odometer"] == 40000


def test_completing_a_pm_a_rebases_the_counters_on_the_current_odometer(api):
    """PRD §3.2: "Completion takes the order `IN_SHOP → COMPLETED` and returns the asset
    `IN_SHOP → AVAILABLE`; a coordinator may record the `performed_odometer_miles` observed
    in the bay, and when the completed work is a `PM_A` or `PM_B` on a tractor the PM
    baseline resets — `pm_last_service_odometer` becomes the tractor's current
    `odometer_miles`, `miles_since_pm` becomes zero, and `pm_hold` clears to false."

    Design: Corner/state_machines/pm_work_order_start_and_complete_reset_the_tractor_pm_counters
    """
    ctx = _tractor_with_an_inspection_and_a_pm_booking()
    _run_the_shop_visit(ctx["inspection"]["id"])
    started, finished = _run_the_shop_visit(ctx["preventive"]["id"])
    assert started["status"] == "IN_SHOP"
    assert finished["status"] == "COMPLETED"

    after = get_success_data(api.get_tractor(ctx["tractor"]["id"], MAINTENANCE))
    assert after["status"] == "AVAILABLE"
    assert after["odometer_miles"] == 50000
    assert after["pm_last_service_odometer"] == 50000
    assert after["miles_since_pm"] == 0
    assert after["pm_hold"] is False


def test_the_plan_gate_asks_for_a_crew_before_it_asks_for_a_delivery(api):
    """PRD §3.5: "It must be fully crewed — a driver, a tractor and a trailer all present —
    otherwise `ERR_TRIP_NOT_STAFFED`. It must carry at least one `DELIVERY` stop, otherwise
    `ERR_TRIP_HAS_NO_STOPS`."

    Design: Corner/state_machines/plan_demands_staffing_before_it_looks_at_stops
    """
    ctx = setup_base_fleet("s6")
    trip = new_trip(ctx["domicile"]["id"], trip_code="TRIP-SM6",
                    planned_start_at="2026-08-20T06:00:00Z")
    # A single FUEL stop gives the trip a planned end without giving it a delivery.
    add_other_stop(trip["id"], "FUEL", 1, "2026-08-20T08:00:00Z", "2026-08-20T08:25:00Z",
                   120, 100)

    validate_error(api.plan_trip(trip["id"], PLANNER), ApiErrorId.ERR_TRIP_NOT_STAFFED, 409)

    staffed = assign_resources(trip["id"], ctx["driver"]["id"], ctx["tractor"]["id"],
                               ctx["trailer"]["id"])
    assert staffed["driver_id"] == ctx["driver"]["id"]

    validate_error(api.plan_trip(trip["id"], PLANNER), ApiErrorId.ERR_TRIP_HAS_NO_STOPS, 409)
    assert read_trip(trip["id"])["plan_status"] == "DRAFT"


def _driver_carrying_one_speeding_exception():
    """D-SM7 holds a severity-2 SPEEDING event: 3 x 2 = 6 points, so the score is 94."""
    set_clock()
    domicile = new_domicile(domicile_code="DOM-SM7", region_code="MIDWEST")
    pay_plan = new_pay_plan(plan_code="MILE-C")
    driver = new_driver(domicile["id"], pay_plan["id"], driver_code="D-SM7",
                        seniority_date="2019-03-01")
    event = new_telematics_event(driver["id"], "SPEEDING", 2, "2026-07-25T10:00:00Z")
    return {"driver": driver, "event": event}


def test_coaching_retires_the_points_and_stamps_the_logical_clock(api):
    """PRD §3.9: "Coaching sets the event's `coached` to true, stamps `coached_at` from the
    logical clock and `coached_by_user_id` from the acting `X-User-ID`, lowers the driver's
    `open_penalty_points` by that event's `penalty_points`, recomputes `safety_score`, and
    clears `coaching_hold` when the recomputed score reaches 70 or above."

    Design: Corner/state_machines/coaching_an_already_coached_event_is_refused
    """
    ctx = _driver_carrying_one_speeding_exception()
    assert ctx["event"]["penalty_points"] == 6
    assert ctx["event"]["coached"] is False
    assert read_driver(ctx["driver"]["id"])["safety_score"] == 94

    coached = validate_success(
        api.coach_telematics_event(
            ctx["event"]["id"], {"coaching_note": "reviewed dash cam"}, COACH
        )
    )
    assert coached["coached"] is True
    # The stamp comes from the logical clock, not from the event's occurred_at.
    assert coached["coached_at"].startswith("2026-08-01T00:00:00")
    assert coached["coached_by_user_id"] == "user-safety-1"

    standing = read_driver(ctx["driver"]["id"])
    assert standing["open_penalty_points"] == 0
    assert standing["safety_score"] == 100
    assert standing["coaching_hold"] is False


def test_a_second_coaching_of_the_same_event_credits_nothing(api):
    """PRD §3.9: "The event must not already be coached — a second attempt is
    `ERR_ALREADY_COACHED` — and the driver must not be `TERMINATED`, which is
    `ERR_DRIVER_NOT_ACTIVE`."

    Design: Corner/state_machines/coaching_an_already_coached_event_is_refused
    """
    ctx = _driver_carrying_one_speeding_exception()
    get_success_data(
        api.coach_telematics_event(ctx["event"]["id"], {"coaching_note": "reviewed"}, COACH)
    )

    validate_error(
        api.coach_telematics_event(
            ctx["event"]["id"], {"coaching_note": "reviewed again"}, COACH
        ),
        ApiErrorId.ERR_ALREADY_COACHED,
        409,
    )
    standing = read_driver(ctx["driver"]["id"])
    assert standing["open_penalty_points"] == 0
    assert standing["safety_score"] == 100
    assert get_success_data(
        api.get_telematics_event(ctx["event"]["id"], SAFETY)
    )["coached"] is True


def _board_with_one_bid_closing_on_august_tenth():
    ctx = setup_base_fleet("s8", driver_overrides={"seniority_date": "2017-04-10"})
    posting = new_route_posting(ctx["domicile"]["id"], PUBLISHER, route_code="RT-SM8",
                                weekly_miles=2000, weekly_stops=16,
                                start_effective_date="2026-09-07",
                                bid_close_at="2026-08-10T00:00:00Z")
    bid = place_bid(ctx["driver"]["id"], posting["id"], posting["version"])
    return {"ctx": ctx, "posting": posting, "bid": bid}


def test_an_award_one_minute_before_the_close_is_refused(api):
    """PRD §3.9: "The logical clock must have reached `bid_close_at`, and an award attempted
    while bidding is still open is `ERR_BID_WINDOW_OPEN`."

    Design: Corner/state_machines/awarding_before_the_bid_window_closes_is_refused
    """
    ctx = _board_with_one_bid_closing_on_august_tenth()
    set_clock("2026-08-09T23:59:00Z")

    validate_error(
        api.award_route_posting(ctx["posting"]["id"], AWARDER),
        ApiErrorId.ERR_BID_WINDOW_OPEN,
        409,
    )
    unmoved = read_posting(ctx["posting"]["id"])
    assert unmoved["status"] == "OPEN"
    assert unmoved["bid_count"] == 1
    assert unmoved["awarded_driver_id"] is None


def test_the_award_lands_the_moment_the_clock_reaches_the_close(api):
    """PRD §3.9: "The winning bid moves `SUBMITTED → AWARDED`, every other `SUBMITTED` bid
    moves to `PASSED_OVER`, the posting's `awarded_driver_id` is set to the winner's driver,
    the posting moves `OPEN → AWARDED`, its `bid_count` is set outright to zero, and its
    `version` advances."

    Design: Corner/state_machines/awarding_before_the_bid_window_closes_is_refused
    """
    ctx = _board_with_one_bid_closing_on_august_tenth()
    set_clock("2026-08-09T23:59:00Z")
    validate_error(
        api.award_route_posting(ctx["posting"]["id"], AWARDER),
        ApiErrorId.ERR_BID_WINDOW_OPEN,
        409,
    )

    set_clock("2026-08-10T00:00:00Z")
    awarded = validate_success(api.award_route_posting(ctx["posting"]["id"], AWARDER))
    assert awarded["status"] == "AWARDED"
    assert awarded["awarded_driver_id"] == ctx["ctx"]["driver"]["id"]
    assert awarded["bid_count"] == 0
    assert get_success_data(
        api.get_route_bid(ctx["bid"]["id"], MANAGER)
    )["status"] == "AWARDED"


def _one_store_with_a_committed_trip_and_a_waiting_one():
    """TRIP-SM9A is PLANNED; TRIP-SM9B is staffed and stopped but not yet committed."""
    ctx = setup_base_fleet("s9")
    order_b = new_order(ctx["store"]["id"], priority=2)
    driver_b = new_driver(ctx["domicile"]["id"], ctx["pay_plan"]["id"],
                          driver_code="D-SM9B", seniority_date="2019-04-01")
    tractor_b = new_tractor(ctx["domicile"]["id"], unit_code="TR-SM9B")
    trailer_b = new_trailer(ctx["domicile"]["id"], trailer_code="TL-SM9B")

    trip_a = new_trip(ctx["domicile"]["id"], trip_code="TRIP-SM9A",
                      planned_start_at="2026-08-20T06:00:00Z")
    stop_a = add_delivery_stop(trip_a["id"], ctx["store"]["id"], ctx["order"]["id"], 1,
                               "2026-08-20T08:00:00Z", "2026-08-20T09:15:00Z", 120, 100, 600)
    assign_resources(trip_a["id"], ctx["driver"]["id"], ctx["tractor"]["id"],
                     ctx["trailer"]["id"])
    planned_a = plan_trip(trip_a["id"])

    trip_b = new_trip(ctx["domicile"]["id"], trip_code="TRIP-SM9B",
                      planned_start_at="2026-08-20T10:00:00Z")
    add_delivery_stop(trip_b["id"], ctx["store"]["id"], order_b["id"], 1,
                      "2026-08-20T12:00:00Z", "2026-08-20T13:15:00Z", 120, 100, 600)
    assign_resources(trip_b["id"], driver_b["id"], tractor_b["id"], trailer_b["id"])

    return {"ctx": ctx, "trip_a": trip_a, "stop_a": stop_a, "planned_a": planned_a,
            "trip_b": trip_b}


def _suspend(store_id):
    return validate_success(api_client.set_store_status(store_id, {"status": "SUSPENDED"}, MANAGER))


def test_suspending_a_store_leaves_the_committed_trip_exactly_as_it_was(api):
    """PRD §3.1: "Suspension is deliberately toothless towards work already committed: no
    cascade fires, trips already planned keep every stop they had, and the only consequence
    is that a *new* plan commitment touching a `SUSPENDED` store is refused with
    `ERR_STORE_SUSPENDED`."

    Design: Corner/state_machines/store_suspension_spares_committed_trips_and_blocks_new_ones
    """
    ctx = _one_store_with_a_committed_trip_and_a_waiting_one()
    assert ctx["planned_a"]["plan_status"] == "PLANNED"

    suspended = _suspend(ctx["ctx"]["store"]["id"])
    assert suspended["status"] == "SUSPENDED"
    assert suspended["open_scheduled_cases"] == 600

    assert read_trip(ctx["trip_a"]["id"])["plan_status"] == "PLANNED"
    assert get_success_data(
        api.get_trip_stop(ctx["stop_a"]["id"], PLANNER)
    )["status"] == "PLANNED"
    assert get_success_data(
        api.get_order(ctx["ctx"]["order"]["id"], PLANNER)
    )["status"] == "SCHEDULED"


def test_the_suspended_store_refuses_a_fresh_commitment_and_fresh_demand(api):
    """PRD §3.5: "Every `DELIVERY` stop's store must be `ACTIVE`, otherwise
    `ERR_STORE_SUSPENDED`, and every `DELIVERY` stop's order must still be `UNSCHEDULED`,
    otherwise `ERR_ORDER_NOT_SCHEDULABLE`." And PRD §3.4: "Raising an order against a
    `SUSPENDED` store is refused with `ERR_STORE_SUSPENDED`."

    Design: Corner/state_machines/store_suspension_spares_committed_trips_and_blocks_new_ones
    """
    ctx = _one_store_with_a_committed_trip_and_a_waiting_one()
    _suspend(ctx["ctx"]["store"]["id"])

    validate_error(
        api.plan_trip(ctx["trip_b"]["id"], PLANNER),
        ApiErrorId.ERR_STORE_SUSPENDED,
        409,
    )
    assert read_trip(ctx["trip_b"]["id"])["plan_status"] == "DRAFT"

    validate_error(
        api.create_order(
            {
                "store_id": ctx["ctx"]["store"]["id"],
                "cases": 100,
                "weight_lbs": 2200,
                "requested_window_start": "2026-08-21T06:00:00Z",
                "requested_window_end": "2026-08-21T18:00:00Z",
                "temperature_mode": "DRY",
                "priority": 1,
            },
            PLANNER,
        ),
        ApiErrorId.ERR_STORE_SUSPENDED,
        409,
    )
    assert read_store(ctx["ctx"]["store"]["id"])["open_scheduled_cases"] == 600


def _dispatched_trip_with_a_delivery_and_a_fuel_stop():
    ctx = setup_base_fleet("s10")
    trip = new_trip(ctx["domicile"]["id"], trip_code="TRIP-SM10",
                    planned_start_at="2026-08-20T06:00:00Z")
    first = add_delivery_stop(trip["id"], ctx["store"]["id"], ctx["order"]["id"], 1,
                              "2026-08-20T08:00:00Z", "2026-08-20T09:15:00Z", 120, 100, 600)
    second = add_other_stop(trip["id"], "FUEL", 2, "2026-08-20T10:00:00Z",
                            "2026-08-20T10:25:00Z", 45, 38)
    assign_resources(trip["id"], ctx["driver"]["id"], ctx["tractor"]["id"],
                     ctx["trailer"]["id"])
    planned = plan_trip(trip["id"])
    dispatched = dispatch_trip(trip["id"])
    return {"ctx": ctx, "trip": trip, "first": first, "second": second,
            "planned": planned, "dispatched": dispatched}


def test_the_first_arrival_bubbles_the_parent_trip_into_progress(api):
    """PRD §3.7: "The **first** arrival on a trip that is still `DISPATCHED` bubbles the
    parent upward — the trip moves `DISPATCHED → IN_PROGRESS` as a consequence of the child
    stop's transition, and the stop's own `version` advances."

    Design: Corner/state_machines/first_stop_arrival_bubbles_the_trip_to_in_progress
    """
    ctx = _dispatched_trip_with_a_delivery_and_a_fuel_stop()
    assert ctx["planned"]["stop_count"] == 2
    # Drive 120 + 45, service 75 + 25, no mandatory break.
    assert ctx["planned"]["planned_duty_minutes"] == 265
    assert ctx["planned"]["plan_status"] == "PLANNED"
    assert ctx["dispatched"]["plan_status"] == "DISPATCHED"

    driver_headers = make_driver_headers(ctx["ctx"]["driver"]["id"])
    arrived = validate_success(
        api.arrive_at_stop(ctx["first"]["id"], driver_headers,
                           {"actual_arrival_at": "2026-08-20T08:02:00Z"})
    )
    assert arrived["status"] == "ARRIVED"
    assert arrived["version"] == 2
    # The bubble has no endpoint of its own and is visible in the very next read.
    assert read_trip(ctx["trip"]["id"])["plan_status"] == "IN_PROGRESS"


def test_the_second_arrival_finds_the_trip_already_in_progress(api):
    """PRD §3.7: "The owning trip must be in `DISPATCHED` or `IN_PROGRESS`, and the stop
    itself must be in `PLANNED`; either failure is `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/first_stop_arrival_bubbles_the_trip_to_in_progress
    """
    ctx = _dispatched_trip_with_a_delivery_and_a_fuel_stop()
    driver_headers = make_driver_headers(ctx["ctx"]["driver"]["id"])
    get_success_data(
        api.arrive_at_stop(ctx["first"]["id"], driver_headers,
                           {"actual_arrival_at": "2026-08-20T08:02:00Z"})
    )
    finished = validate_success(
        api.complete_stop(
            ctx["first"]["id"],
            {"cases_handled": 600, "actual_departure_at": "2026-08-20T09:20:00Z"},
            driver_headers,
        )
    )
    assert finished["status"] == "COMPLETED"

    second = validate_success(
        api.arrive_at_stop(ctx["second"]["id"], driver_headers,
                           {"actual_arrival_at": "2026-08-20T10:05:00Z"})
    )
    assert second["status"] == "ARRIVED"
    assert read_trip(ctx["trip"]["id"])["plan_status"] == "IN_PROGRESS"
