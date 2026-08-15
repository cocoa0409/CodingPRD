"""Trip clocks: weather holds, rest/unload, confinement, washout freshness.

Covers PRD §3.5 (hold cycles, rest-unload cycles, confinement limit, weather
gate) and §3.2 (the 96-hour washout validity window).
"""
from test_helpers import (
    TEST_USERS,
    assert_ts_eq,
    create_weather_hold_payload,
    make_driver_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId as E
from test_helpers.fixtures import (
    create_trailer,
    get_load,
    get_settlement_of_load,
    get_trailer,
    set_clock,
    setup_assigned_load,
    setup_in_transit_load,
    wash_trailer,
)

ADMIN = TEST_USERS["admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]


class TestCyclicStateMachine:
    def test_two_weather_hold_cycles_and_rest_unload(self, api):
        """PRD §3.5: "A `Dispatcher`, or the assigned `Driver` on their own
        load, may place a hold while the load is `ASSIGNED` or `IN_TRANSIT`
        (any other state fails with `ERR_LOAD_NOT_HOLDABLE`, HTTP 409)."
        PRD §3.5: "The release sets `released_at` to now, increments the hold's
        `version`, and resumes the load along one of two sibling branches with
        equal effect on the load `version` (incremented by 1 in both): if the
        load never departed — `departed_at` is null — it returns `WEATHER_HOLD
        → ASSIGNED`; if the load was held in transit — `departed_at` is set —
        the server appends a system `DRIVING_ON` event and the load returns
        `WEATHER_HOLD → IN_TRANSIT`."
        PRD §3.5: "Resuming transit moves `REST_UNLOAD → IN_TRANSIT` (any other
        state fails with `ERR_LOAD_NOT_REST_UNLOAD`) and is allowed only once
        at least 300 minutes (five hours) have elapsed since
        `rest_unload_started_at` — exactly 300 minutes qualifies, anything less
        fails with `ERR_INSUFFICIENT_REST_UNLOAD` (HTTP 422). A qualifying
        resume resets the confinement clock: `confinement_anchor_at` is set to
        now, `rest_unload_started_at` is cleared to null, a system `DRIVING_ON`
        is appended, and the load `version` increments."

        Design: Difficulty/non_linear_state_machine/load_transit_weather_hold_and_rest_unload_cycles
        """
        ctx = setup_in_transit_load()
        load_id = ctx["load"]["id"]
        driver_id = ctx["driver"]["id"]

        # first hold cycle: HEAT hold in transit at 09:00, released 10:00
        set_clock("2026-08-02T09:00:00Z")
        h1 = validate_success(
            api.create_weather_hold(
                load_id, create_weather_hold_payload(
                    hold_type="HEAT", temperature_f=96),
                make_driver_headers(driver_id)), 201)
        assert get_load(load_id)["status"] == "WEATHER_HOLD"
        set_clock("2026-08-02T10:00:00Z")
        validate_success(api.release_weather_hold(h1["id"], DISP), 200)
        assert get_load(load_id)["status"] == "IN_TRANSIT"

        # rest/unload cycle: stop at 18:00, resume exactly 300 minutes later
        set_clock("2026-08-02T18:00:00Z")
        validate_success(api.rest_unload(load_id,
                                         make_driver_headers(driver_id)), 200)
        assert get_load(load_id)["status"] == "REST_UNLOAD"
        set_clock("2026-08-02T23:00:00Z")
        validate_success(api.resume_transit(load_id,
                                            make_driver_headers(driver_id)),
                         200)
        after_resume = get_load(load_id)
        assert after_resume["status"] == "IN_TRANSIT"
        # 18:00 + 300 min = 23:00: exactly at the inclusive minimum, and the
        # confinement clock restarts at the resume instant
        assert_ts_eq(after_resume["confinement_anchor_at"],
                     "2026-08-02T23:00:00Z", "confinement_anchor_at")

        # second hold cycle: COLD hold at 23:30, released 2026-08-03T01:00
        set_clock("2026-08-02T23:30:00Z")
        h2 = validate_success(
            api.create_weather_hold(
                load_id, create_weather_hold_payload(
                    hold_type="COLD", temperature_f=-2),
                make_driver_headers(driver_id)), 201)
        set_clock("2026-08-03T01:00:00Z")
        validate_success(api.release_weather_hold(h2["id"], DISP), 200)

        assert get_load(load_id)["status"] == "IN_TRANSIT"
        holds, meta = validate_paginated(api.list_weather_holds(load_id, ADMIN))
        assert len(holds) == 2
        assert all(h["status"] == "RELEASED" for h in holds)

    def test_hold_release_after_departure_resumes_in_transit(self, api):
        """PRD §3.5: "if the load was held in transit — `departed_at` is set —
        the server appends a system `DRIVING_ON` event and the load returns
        `WEATHER_HOLD → IN_TRANSIT`."
        PRD §3.5: "A `WeatherHold` is created `ACTIVE` — its `status` is
        `ACTIVE` while `released_at` is null — the load moves to
        `WEATHER_HOLD`, and the load `version` increments by 1."

        Design: Difficulty/non_linear_state_machine/load_transit_weather_hold_and_rest_unload_cycles
        """
        ctx = setup_in_transit_load()
        load_id = ctx["load"]["id"]
        driver_id = ctx["driver"]["id"]

        set_clock("2026-08-02T09:00:00Z")
        hold = validate_success(
            api.create_weather_hold(
                load_id, create_weather_hold_payload(
                    hold_type="HEAT", temperature_f=97),
                make_driver_headers(driver_id)), 201)
        assert hold["status"] == "ACTIVE"
        assert hold["released_at"] is None
        assert get_load(load_id)["status"] == "WEATHER_HOLD"

        set_clock("2026-08-02T11:00:00Z")
        released = validate_success(
            api.release_weather_hold(hold["id"], DISP), 200)
        assert released["status"] == "RELEASED"
        assert released["released_at"] is not None
        assert get_load(load_id)["status"] == "IN_TRANSIT"


class TestConfinementBoundary:
    def test_confinement_arrive_at_exactly_1680_allowed(self, api):
        """PRD §3.5: "The confinement rule binds here: the span from
        `confinement_anchor_at` to now must not exceed 1680 minutes
        (twenty-eight hours) — exactly 1680 minutes is allowed, any more is
        rejected with `ERR_CONFINEMENT_LIMIT_EXCEEDED` (HTTP 422)."
        PRD §3.5: "Arrival sets `arrived_at` to now, appends a system
        `DRIVING_OFF`, and increments the load `version`."

        Design: Corner/calculations/confinement_arrive_at_exactly_1680_allowed
        """
        ctx = setup_in_transit_load(planned_duration_hours=30,
                                    loaded_miles=1500)
        # depart 2026-08-02T08:00 -> exactly 1680 minutes later
        set_clock("2026-08-03T12:00:00Z")
        arrived = validate_success(
            api.arrive(ctx["load"]["id"],
                       make_driver_headers(ctx["driver"]["id"])), 200)
        assert arrived["status"] == "ARRIVED"
        assert_ts_eq(arrived["arrived_at"], "2026-08-03T12:00:00Z",
                     "arrived_at")

    def test_arrive_after_1680_minutes_rejected(self, api):
        """PRD §3.5: "The confinement rule binds here: the span from
        `confinement_anchor_at` to now must not exceed 1680 minutes
        (twenty-eight hours) — exactly 1680 minutes is allowed, any more is
        rejected with `ERR_CONFINEMENT_LIMIT_EXCEEDED` (HTTP 422)."

        Design: Corner/errors/arrive_after_1680_minutes_rejected
        """
        ctx = setup_in_transit_load(planned_duration_hours=30,
                                    loaded_miles=1500)
        # one minute past the 1680-minute limit
        set_clock("2026-08-03T12:01:00Z")
        resp = api.arrive(ctx["load"]["id"],
                          make_driver_headers(ctx["driver"]["id"]))
        validate_error(resp, E.ERR_CONFINEMENT_LIMIT_EXCEEDED)
        assert get_load(ctx["load"]["id"])["status"] == "IN_TRANSIT"


class TestRestUnloadBoundary:
    def test_rest_unload_resume_at_299_minutes_rejected(self, api):
        """PRD §3.5: "Resuming transit moves `REST_UNLOAD → IN_TRANSIT` (any
        other state fails with `ERR_LOAD_NOT_REST_UNLOAD`) and is allowed only
        once at least 300 minutes (five hours) have elapsed since
        `rest_unload_started_at` — exactly 300 minutes qualifies, anything less
        fails with `ERR_INSUFFICIENT_REST_UNLOAD` (HTTP 422)."

        Design: Corner/calculations/rest_unload_resume_at_299_minutes_rejected
        """
        ctx = setup_in_transit_load()
        set_clock("2026-08-02T18:00:00Z")
        validate_success(
            api.rest_unload(ctx["load"]["id"],
                            make_driver_headers(ctx["driver"]["id"])), 200)
        # 18:00 + 299 minutes
        set_clock("2026-08-02T22:59:00Z")
        resp = api.resume_transit(ctx["load"]["id"],
                                  make_driver_headers(ctx["driver"]["id"]))
        validate_error(resp, E.ERR_INSUFFICIENT_REST_UNLOAD)
        assert get_load(ctx["load"]["id"])["status"] == "REST_UNLOAD"


class TestWashoutFreshness:
    def test_washout_stale_after_exactly_96h(self, api):
        """PRD §3.2: "Otherwise it is `CLEAN` while the current time is at or
        before `last_washed_at` plus 96 hours — the boundary is inclusive, so a
        trailer at exactly 96 hours since its wash is still clean — and `STALE`
        once that moment has passed."
        PRD §3.2: "Recording a wash sets the trailer's `last_washed_at` to
        `washed_at`, clears `dirtied_at` to null, sets `washout_valid_until` to
        `washed_at` plus 96 hours, and recomputes `washout_status`."

        Design: Corner/calculations/washout_stale_after_exactly_96h
        """
        set_clock("2026-08-01T01:00:00Z")
        tt = create_trailer()
        wash_trailer(tt["trailer"]["id"], washed_at="2026-08-01T00:30:00Z",
                     method="STEAM")

        # exactly +96h: still CLEAN (inclusive boundary)
        set_clock("2026-08-05T00:30:00Z")
        trailer = get_trailer(tt["trailer"]["id"])
        assert trailer["washout_status"] == "CLEAN"
        assert_ts_eq(trailer["washout_valid_until"], "2026-08-05T00:30:00Z",
                     "washout_valid_until")

        # one second later: STALE
        set_clock("2026-08-05T00:30:01Z")
        assert get_trailer(tt["trailer"]["id"])["washout_status"] == "STALE"

    def test_washout_in_future_rejected(self, api):
        """PRD §3.2: "A `WashoutOperator` or `CarrierAdmin` records a wash with
        its `washed_at` completion timestamp — which must not be later than the
        current logical time, or the record is rejected with
        `ERR_EVENT_IN_FUTURE` — a `method` of `HIGH_PRESSURE`, `STEAM`, or
        `CHEMICAL`, and an optional `operator_note`."
        PRD §2.5: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`; until it is explicitly set, the clock continues
        to report this default and never falls back to wall-clock time."

        Design: Corner/validations/washout_in_future_rejected
        """
        from test_helpers import create_washout_payload
        # the logical clock was never set: it reads 2026-08-01T00:00:00Z
        tt = create_trailer()
        resp = api.create_washout(
            tt["trailer"]["id"],
            create_washout_payload(washed_at="2026-08-01T02:00:00Z",
                                   method="STEAM"),
            TEST_USERS["washout_headers"])
        validate_error(resp, E.ERR_EVENT_IN_FUTURE)
        assert get_trailer(tt["trailer"]["id"])["washout_status"] == "DIRTY"


class TestDepartRequiresFreshWashout:
    def test_depart_one_second_after_washout_expiry_rejected(self, api):
        """PRD §3.5: "the trailer's `washout_status` is `CLEAN` at the current
        time (`ERR_TRAILER_NOT_CLEAN`, HTTP 422)"
        PRD §3.2: "Otherwise it is `CLEAN` while the current time is at or
        before `last_washed_at` plus 96 hours — the boundary is inclusive, so a
        trailer at exactly 96 hours since its wash is still clean — and `STALE`
        once that moment has passed."

        Design: Difficulty/cross_entity_state_dependency/depart_requires_fresh_trailer_washout
        """
        # trailer washed 2026-08-01T00:30:00Z; one second past +96h validity
        ctx = setup_assigned_load(
            planned_departure_at="2026-08-04T08:00:00Z")
        set_clock("2026-08-05T00:30:01Z")
        trailer = get_trailer(ctx["trailer"]["id"])
        assert trailer["washout_status"] == "STALE"

        resp = api.depart(ctx["load"]["id"], {"origin_temperature_f": 70},
                          make_driver_headers(ctx["driver"]["id"]))
        validate_error(resp, E.ERR_TRAILER_NOT_CLEAN)
        assert get_load(ctx["load"]["id"])["status"] == "ASSIGNED"

    def test_depart_within_washout_validity_succeeds(self, api):
        """PRD §3.2: "Recording a wash sets the trailer's `last_washed_at` to
        `washed_at`, clears `dirtied_at` to null, sets `washout_valid_until` to
        `washed_at` plus 96 hours, and recomputes `washout_status`."
        PRD §3.5: "the trailer's `washout_status` is `CLEAN` at the current
        time (`ERR_TRAILER_NOT_CLEAN`, HTTP 422)"

        Design: Difficulty/cross_entity_state_dependency/depart_requires_fresh_trailer_washout
        """
        # washed 2026-08-01T00:30:00Z, departing well inside the 96h window
        ctx = setup_assigned_load()
        trailer = get_trailer(ctx["trailer"]["id"])
        assert trailer["washout_status"] == "CLEAN"
        assert_ts_eq(trailer["washout_valid_until"], "2026-08-05T00:30:00Z",
                     "washout_valid_until")

        set_clock("2026-08-02T08:00:00Z")
        departed = validate_success(
            api.depart(ctx["load"]["id"], {"origin_temperature_f": 70},
                       make_driver_headers(ctx["driver"]["id"])), 200)
        assert departed["status"] == "IN_TRANSIT"


class TestWeatherHoldReleaseTwice:
    def test_release_weather_hold_twice_rejected(self, api):
        """PRD §3.5: "Releasing a hold — again a `Dispatcher` or the load's own
        `Driver` — requires the hold to be `ACTIVE` (`ERR_HOLD_NOT_ACTIVE`,
        HTTP 409; a hold id that does not resolve fails earlier with
        `ERR_HOLD_NOT_FOUND`)."

        Design: Corner/state_machines/release_weather_hold_twice_rejected
        """
        ctx = setup_assigned_load()
        hold = validate_success(
            api.create_weather_hold(
                ctx["load"]["id"],
                create_weather_hold_payload(hold_type="COLD", temperature_f=-3),
                DISP), 201)
        validate_success(api.release_weather_hold(hold["id"], DISP), 200)

        resp = api.release_weather_hold(hold["id"], DISP)
        validate_error(resp, E.ERR_HOLD_NOT_ACTIVE)

        holds, _ = validate_paginated(
            api.list_weather_holds(ctx["load"]["id"], ADMIN))
        assert len(holds) == 1
        assert holds[0]["status"] == "RELEASED"


class TestSwineHeatThreshold:
    def test_weather_swine_heat_threshold_inclusive_at_85f(self, api):
        """PRD §3.5: "the weather gate — departure is forbidden, and a weather
        hold is required instead, when `origin_temperature_f` is at or above
        the species heat threshold (95 for `CATTLE`, 85 for `SWINE`, 90 for
        `SHEEP`, 95 for `HORSES`) or at or below the species cold threshold (0
        for `CATTLE`, 10 for `SWINE`, -5 for `SHEEP`, 5 for `HORSES`), with the
        thresholds inclusive on both sides (`ERR_WEATHER_HOLD_REQUIRED`,
        HTTP 422)."
        PRD §3.6: "`provisional_amount_cents` equals `base_amount_cents`: the
        provisional figure assumes an on-weight delivery, with no shrink
        penalty and no welfare deduction."

        Design: Difficulty/boundary_precision_check/weather_swine_heat_threshold_inclusive_at_85f
        """
        ctx = setup_assigned_load(species="SWINE", head_count=20,
                                  weight_lb=10000)
        set_clock("2026-08-02T08:00:00Z")
        # 85F is exactly the SWINE heat threshold: inclusive -> hold required
        resp = api.depart(ctx["load"]["id"], {"origin_temperature_f": 85},
                          make_driver_headers(ctx["driver"]["id"]))
        validate_error(resp, E.ERR_WEATHER_HOLD_REQUIRED)
        assert get_load(ctx["load"]["id"])["status"] == "ASSIGNED"

        # a dispatcher places the hold instead, then releases it
        hold = validate_success(
            api.create_weather_hold(
                ctx["load"]["id"],
                create_weather_hold_payload(hold_type="HEAT", temperature_f=85),
                DISP), 201)
        validate_success(api.release_weather_hold(hold["id"], DISP), 200)

        # one degree below the threshold departs cleanly
        departed = validate_success(
            api.depart(ctx["load"]["id"], {"origin_temperature_f": 84},
                       make_driver_headers(ctx["driver"]["id"])), 200)
        assert departed["status"] == "IN_TRANSIT"
        s = get_settlement_of_load(ctx["load"]["id"])
        assert s["provisional_amount_cents"] == 150000

    def test_weather_sheep_cold_threshold_inclusive_at_minus_5f(self, api):
        """PRD §3.5: "the weather gate — departure is forbidden, and a weather
        hold is required instead, when `origin_temperature_f` is at or above
        the species heat threshold (95 for `CATTLE`, 85 for `SWINE`, 90 for
        `SHEEP`, 95 for `HORSES`) or at or below the species cold threshold (0
        for `CATTLE`, 10 for `SWINE`, -5 for `SHEEP`, 5 for `HORSES`), with the
        thresholds inclusive on both sides (`ERR_WEATHER_HOLD_REQUIRED`,
        HTTP 422)."

        Design: Difficulty/boundary_precision_check/weather_swine_heat_threshold_inclusive_at_85f
        """
        ctx = setup_assigned_load(species="SHEEP", head_count=40,
                                  weight_lb=40000)
        set_clock("2026-08-02T08:00:00Z")
        # -5F is exactly the SHEEP cold threshold: inclusive -> hold required
        resp = api.depart(ctx["load"]["id"], {"origin_temperature_f": -5},
                          make_driver_headers(ctx["driver"]["id"]))
        validate_error(resp, E.ERR_WEATHER_HOLD_REQUIRED)
        assert get_load(ctx["load"]["id"])["status"] == "ASSIGNED"

        # place and release the hold, then one degree above the threshold
        hold = validate_success(
            api.create_weather_hold(
                ctx["load"]["id"],
                create_weather_hold_payload(hold_type="COLD", temperature_f=-5),
                DISP), 201)
        validate_success(api.release_weather_hold(hold["id"], DISP), 200)

        departed = validate_success(
            api.depart(ctx["load"]["id"], {"origin_temperature_f": -4},
                       make_driver_headers(ctx["driver"]["id"])), 200)
        assert departed["status"] == "IN_TRANSIT"
