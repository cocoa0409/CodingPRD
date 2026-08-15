"""Show execution gates (state, window, freshness, fiscal) and post-flight
flight-log reconciliation."""
from test_helpers import (
    ApiErrorId,
    assign_drone,
    certify_evaluation,
    certify_show_go,
    create_evaluation,
    get_success_data,
    get_show,
    pay_show_in_full,
    post_flight_log,
    post_weather,
    register_drone,
    set_clock,
    setup_authorized_show,
    setup_executed_show,
    setup_go_certified_show,
    setup_ready_show,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

PLANNER = TEST_USERS["planner_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]


class TestExecuteGates:
    def test_execute_from_ready_returns_invalid_state(self, api):
        """PRD: "The show must be `GO_CERTIFIED` (else `ERR_INVALID_STATE`)"
        PRD: "When several validations could reject the same request, they are
        evaluated in a fixed priority order, and the first failing check
        produces the response."

        Design: Corner/state_machines/execute_from_ready_returns_invalid_state
        """
        ctx = setup_ready_show(
            show_overrides={"drone_count_planned": 2},
            design_overrides={"drone_count": 2})
        assert ctx["show"]["lifecycle_status"] == "READY"
        resp = api.execute_show(ctx["show"]["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_execute_unpaid_returns_not_paid_in_full(self, api):
        """PRD: "the commercial gate applies — `payment_status` must be
        `PAID_IN_FULL` (else `ERR_SHOW_NOT_PAID_IN_FULL`)."

        Design: Corner/validations/execute_unpaid_returns_not_paid_in_full
        """
        ctx = setup_go_certified_show(
            show_overrides={"drone_count_planned": 1},
            design_overrides={"drone_count": 1, "duration_sec": 300})
        assert ctx["show"]["lifecycle_status"] == "GO_CERTIFIED"
        set_clock("2026-08-10T19:05:00Z")  # inside the window
        resp = api.execute_show(ctx["show"]["id"], PLANNER)
        # State, window, and freshness all pass; only the fiscal gate fails.
        validate_error(resp, ApiErrorId.ERR_SHOW_NOT_PAID_IN_FULL)

    def test_execute_before_window_returns_outside_window(self, api):
        """PRD: "the logical clock must read at or after `window_start` and
        strictly before `window_end` (else `ERR_OUTSIDE_SHOW_WINDOW`)"

        Design: Corner/validations/execute_before_window_returns_outside_window
        """
        ctx = setup_go_certified_show(
            show_overrides={"drone_count_planned": 1},
            design_overrides={"drone_count": 1, "duration_sec": 300},
            eval_clock="2026-08-10T17:55:00Z",
            reading_at="2026-08-10T17:50:00Z")
        pay_show_in_full(ctx["show"]["id"])
        set_clock("2026-08-10T18:00:00Z")  # 18:00 < window_start 19:00
        resp = api.execute_show(ctx["show"]["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_SHOW_WINDOW)

    def test_execute_with_stale_evaluation_returns_evaluation_stale(self, api):
        """PRD: "a `CERTIFIED` `GO` evaluation whose certification is still
        within the 240-minute freshness window must exist (else
        `ERR_EVALUATION_STALE`)" and "the gap between `certified_at` and the
        current logical-clock reading must not exceed 240 minutes, with an
        evaluation exactly 240 minutes old still acceptable, else
        `ERR_EVALUATION_STALE`."

        Design: Corner/validations/execute_with_stale_evaluation_returns_evaluation_stale
        """
        ctx = setup_go_certified_show(
            show_overrides={"drone_count_planned": 1},
            design_overrides={"drone_count": 1, "duration_sec": 300},
            eval_clock="2026-08-10T15:00:00Z",
            reading_at="2026-08-10T14:40:00Z")
        pay_show_in_full(ctx["show"]["id"])
        # Certified at 15:00; executing at 19:05 is 245 minutes later.
        set_clock("2026-08-10T19:05:00Z")
        resp = api.execute_show(ctx["show"]["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_EVALUATION_STALE)


class TestFlightLogs:
    def test_flight_log_requires_executed_show_and_flown_assignment(self, api):
        """PRD: "The log is accepted only when the show is `EXECUTED` and the
        named drone holds a `FLOWN` slot for that show; otherwise
        `ERR_INVALID_STATE`."
        PRD: "**Cancelling** a show is valid from every lifecycle except the
        terminal `EXECUTED` and `CANCELLED` states (else `ERR_INVALID_STATE`)"
        PRD: "a `max_deviation_m` strictly above 5.0 meters marks the log's
        `flag_status` as `FLAGGED` — it otherwise remains `RECEIVED`"

        Design: Corner/state_machines/flight_log_requires_executed_show_and_flown_assignment
        """
        ctx = setup_authorized_show(
            show_overrides={"drone_count_planned": 1},
            design_overrides={"drone_count": 1, "duration_sec": 300})
        show_id = ctx["show"]["id"]
        drone = register_drone(serial_number="SN-L1")
        assign_drone(show_id, drone["id"], 0, 0)

        # Not yet EXECUTED (the show is READY): the log is refused.
        resp = api.create_flight_log(
            {"show_event_id": show_id, "drone_id": drone["id"],
             "battery_consumed_pct": 30, "max_altitude_reached_ft": 190,
             "max_deviation_m": 1.0}, TEST_USERS["fleet_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        # Drive to EXECUTED.
        pay_show_in_full(show_id)
        set_clock("2026-08-10T18:45:00Z")
        post_weather(ctx["site"]["id"])
        evaluation = create_evaluation(show_id)
        certify_evaluation(evaluation["id"])
        certify_show_go(show_id, evaluation["id"])
        set_clock("2026-08-10T19:05:00Z")
        get_success_data(api.execute_show(show_id, PLANNER))

        # EXECUTED is terminal for cancellation.
        resp = api.cancel_show(show_id, PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        first = post_flight_log(show_id, drone["id"], battery_consumed_pct=30,
                                max_altitude_reached_ft=190, max_deviation_m=1.0)
        assert first["flag_status"] == "RECEIVED"

        # The slot is RECONCILED now; a duplicate log finds no FLOWN slot.
        resp = api.create_flight_log(
            {"show_event_id": show_id, "drone_id": drone["id"],
             "battery_consumed_pct": 10, "max_altitude_reached_ft": 100,
             "max_deviation_m": 0.5}, TEST_USERS["fleet_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_cycle_threshold_sends_drone_to_maintenance(self, api):
        """PRD: "Receipt of a flight log triggers a reconciliation whose order
        of operations is pinned."
        PRD: "Fourth, the drone's `battery_cycle_count` increments by one.
        Fifth, if the cycle count has reached 200, the drone is sent to
        `IN_MAINTENANCE` automatically."
        PRD: "the drone's `charge_pct` is reduced by the log's
        `battery_consumed_pct`, floored at zero."
        PRD: "`battery_cycle_count` may likewise be seeded to register a used
        airframe and defaults to 0."

        Design: Corner/calculations/flight_log_cycle_threshold_sends_drone_to_maintenance
        """
        ctx = setup_authorized_show(
            show_overrides={"drone_count_planned": 1},
            design_overrides={"drone_count": 1, "duration_sec": 300})
        show_id = ctx["show"]["id"]
        drone = register_drone(serial_number="SN-M199", battery_cycle_count=199)
        assign_drone(show_id, drone["id"], 0, 0)
        pay_show_in_full(show_id)
        set_clock("2026-08-10T18:45:00Z")
        post_weather(ctx["site"]["id"])
        evaluation = create_evaluation(show_id)
        certify_evaluation(evaluation["id"])
        certify_show_go(show_id, evaluation["id"])
        set_clock("2026-08-10T19:05:00Z")
        get_success_data(api.execute_show(show_id, PLANNER))

        post_flight_log(show_id, drone["id"], battery_consumed_pct=35,
                        max_altitude_reached_ft=195, max_deviation_m=1.0)
        after = validate_success(api.get_drone(drone["id"],
                                               TEST_USERS["fleet_manager_headers"]))
        assert after["battery_cycle_count"] == 200, "199 seeded + 1 flight"
        assert after["charge_pct"] == 65, "100 - 35"
        assert after["status"] == "IN_MAINTENANCE", \
            "reaching 200 cycles overrides the release-to-AVAILABLE step"

    def test_deviation_flag_auto_files_minor_incident(self, api):
        """PRD: "a `max_deviation_m` strictly above 5.0 meters marks the log's
        `flag_status` as `FLAGGED` — it otherwise remains `RECEIVED` — and
        auto-files an incident report: `severity` `MINOR`, `source`
        `AUTO_DEVIATION`, status `FILED`, linked to this drone and show, with
        `filed_by_user_id` recorded as `SYSTEM`."

        Design: Corner/endpoints/deviation_flag_auto_files_minor_incident
        """
        ctx = setup_executed_show(
            show_overrides={"drone_count_planned": 2},
            design_overrides={"drone_count": 2, "duration_sec": 300})
        show_id = ctx["show"]["id"]
        d1, d2 = ctx["drones"]

        flagged = post_flight_log(show_id, d1["id"], max_deviation_m=6.0)
        clean = post_flight_log(show_id, d2["id"], max_deviation_m=5.0)
        assert flagged["flag_status"] == "FLAGGED", "6.0 > 5.0 (strict)"
        assert clean["flag_status"] == "RECEIVED", "5.0 is not > 5.0"

        data, meta = validate_paginated(
            api.list_incident_reports(SAFETY, params={"show_event_id": show_id}))
        assert meta["total_count"] == 1, "exactly one auto-filed incident"
        incident = data[0]
        assert incident["severity"] == "MINOR"
        assert incident["source"] == "AUTO_DEVIATION"
        assert incident["status"] == "FILED"
        assert incident["drone_id"] == d1["id"]
        assert incident["filed_by_user_id"] == "SYSTEM"
