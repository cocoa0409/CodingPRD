"""Response drills: state machine, thresholds, half-open overlap."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_certified_drill,
    create_response_drill_payload,
    execute_drill_payload,
    get_success_data,
    set_clock,
    setup_compliant_index_c_airport,
    setup_profile_only,
    validate_error,
    validate_success,
)

AM = TEST_USERS["airport_manager_headers"]
AC = TEST_USERS["arff_chief_headers"]


class TestDrillInitialState:
    def test_drill_initial_state_scheduled_outcome_null(self, api):
        """PRD §3.7: "A scheduled drill carries
        `first_vehicle_arrival_seconds` and `all_vehicles_arrival_seconds`
        unset until execute, `executed_at` null, and `outcome` null; its
        `status` begins at `SCHEDULED`."

        Design: Corner/state_machines/sm_drill_initial_state_scheduled
        """
        setup_profile_only()
        resp = api.create_response_drill(
            create_response_drill_payload(
                runway_designator="09L",
                scheduled_start="2026-05-03T10:00:00Z",
                scheduled_end="2026-05-03T11:00:00Z",
            ),
            AC,
        )
        d = validate_success(resp, expected_status=201)
        assert d["status"] == "SCHEDULED"
        assert d["outcome"] is None
        assert d["executed_at"] is None


class TestDrillCertifyFromScheduledRejected:
    def test_certify_scheduled_drill_rejected(self, api):
        """PRD §3.7: "Certification moves it to `CERTIFIED` and is gated on
        the drill currently being `EXECUTED` (otherwise
        `ERR_DRILL_NOT_CERTIFIABLE`)..."

        Design: Corner/state_machines/sm_drill_certify_from_scheduled_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        setup_profile_only()
        resp = api.create_response_drill(
            create_response_drill_payload(
                runway_designator="09L",
                scheduled_start="2026-05-03T10:00:00Z",
                scheduled_end="2026-05-03T11:00:00Z",
            ),
            AC,
        )
        d = validate_success(resp, expected_status=201)
        resp = api.certify_response_drill(d["id"], AC)
        validate_error(resp, ApiErrorId.ERR_DRILL_NOT_CERTIFIABLE)
        d2 = get_success_data(api.get_response_drill(d["id"], AC))
        assert d2["status"] == "SCHEDULED"


class TestDrillFailTerminalLockdown:
    def test_failed_drill_execute_and_certify_rejected(self, api):
        """PRD §3.7: "Both `CERTIFIED` and `FAILED` are terminal."

        Design: Corner/state_machines/sm_drill_fail_terminal_lockdown
        """
        set_clock("2026-05-01T00:00:00Z")
        setup_profile_only()
        resp = api.create_response_drill(
            create_response_drill_payload(
                runway_designator="09L",
                scheduled_start="2026-05-03T10:00:00Z",
                scheduled_end="2026-05-03T11:00:00Z",
            ),
            AC,
        )
        d = validate_success(resp, expected_status=201)
        set_clock("2026-05-03T10:30:00Z")
        api.execute_response_drill(
            d["id"],
            execute_drill_payload(first_vehicle_arrival_seconds=200,
                                  all_vehicles_arrival_seconds=220),
            AC,
        )
        resp = api.fail_response_drill(d["id"], AC)
        d = validate_success(resp)
        assert d["status"] == "FAILED"

        r1 = api.execute_response_drill(
            d["id"],
            execute_drill_payload(first_vehicle_arrival_seconds=100,
                                  all_vehicles_arrival_seconds=200),
            AC,
        )
        validate_error(r1, ApiErrorId.ERR_DRILL_NOT_EXECUTABLE)
        r2 = api.certify_response_drill(d["id"], AC)
        validate_error(r2, ApiErrorId.ERR_DRILL_NOT_CERTIFIABLE)


class TestDrillFirstVehicle180Boundary:
    def test_first_vehicle_exactly_180_passes_and_certifies(self, api):
        """PRD §3.7: "`PASS` exactly when `first_vehicle_arrival_seconds` is
        at most 180 and `all_vehicles_arrival_seconds` is at most 240;
        otherwise `FAIL`. The thresholds are inclusive — exactly 180 and
        exactly 240 both pass."

        Design: Difficulty/boundary_precision_check/bp_drill_first_vehicle_180_seconds_boundary
        """
        setup_compliant_index_c_airport()
        # Schedule two drills in disjoint windows
        d1 = validate_success(
            api.create_response_drill(
                create_response_drill_payload(
                    runway_designator="09L",
                    scheduled_start="2026-05-02T10:00:00Z",
                    scheduled_end="2026-05-02T11:00:00Z",
                ),
                AC,
            ),
            expected_status=201,
        )
        set_clock("2026-05-02T10:30:00Z")
        resp = api.execute_response_drill(
            d1["id"],
            execute_drill_payload(first_vehicle_arrival_seconds=180,
                                  all_vehicles_arrival_seconds=240),
            AC,
        )
        d1_exec = validate_success(resp)
        assert d1_exec["outcome"] == "PASS"
        resp = api.certify_response_drill(d1["id"], AC)
        d1_cert = validate_success(resp)
        assert d1_cert["status"] == "CERTIFIED"

    def test_first_vehicle_181_fails_and_certify_rejected(self, api):
        """PRD §3.7: "`PASS` exactly when `first_vehicle_arrival_seconds` is
        at most 180 and `all_vehicles_arrival_seconds` is at most 240;
        otherwise `FAIL`."

        Design: Difficulty/boundary_precision_check/bp_drill_first_vehicle_180_seconds_boundary
        """
        setup_compliant_index_c_airport()
        d2 = validate_success(
            api.create_response_drill(
                create_response_drill_payload(
                    runway_designator="09L",
                    scheduled_start="2026-05-02T12:00:00Z",
                    scheduled_end="2026-05-02T13:00:00Z",
                ),
                AC,
            ),
            expected_status=201,
        )
        set_clock("2026-05-02T12:30:00Z")
        resp = api.execute_response_drill(
            d2["id"],
            execute_drill_payload(first_vehicle_arrival_seconds=181,
                                  all_vehicles_arrival_seconds=200),
            AC,
        )
        d2_exec = validate_success(resp)
        assert d2_exec["outcome"] == "FAIL"
        resp = api.certify_response_drill(d2["id"], AC)
        validate_error(resp, ApiErrorId.ERR_RESPONSE_TIME_EXCEEDED)


class TestDrillAllVehicles240Boundary:
    def test_all_vehicles_240_passes_241_fails(self, api):
        """PRD §3.7: "`PASS` exactly when `first_vehicle_arrival_seconds` is
        at most 180 and `all_vehicles_arrival_seconds` is at most 240;
        otherwise `FAIL`. The thresholds are inclusive — exactly 180 and
        exactly 240 both pass."

        Design: Corner/calculations/calc_drill_all_vehicles_240_boundary
        """
        set_clock("2026-05-01T00:00:00Z")
        setup_profile_only()
        d1 = validate_success(
            api.create_response_drill(
                create_response_drill_payload(
                    runway_designator="09L",
                    scheduled_start="2026-05-03T10:00:00Z",
                    scheduled_end="2026-05-03T11:00:00Z",
                ),
                AC,
            ),
            expected_status=201,
        )
        d2 = validate_success(
            api.create_response_drill(
                create_response_drill_payload(
                    runway_designator="09L",
                    scheduled_start="2026-05-03T12:00:00Z",
                    scheduled_end="2026-05-03T13:00:00Z",
                ),
                AC,
            ),
            expected_status=201,
        )
        set_clock("2026-05-03T10:30:00Z")
        resp1 = api.execute_response_drill(
            d1["id"],
            execute_drill_payload(first_vehicle_arrival_seconds=100,
                                  all_vehicles_arrival_seconds=240),
            AC,
        )
        assert validate_success(resp1)["outcome"] == "PASS"

        set_clock("2026-05-03T12:30:00Z")
        resp2 = api.execute_response_drill(
            d2["id"],
            execute_drill_payload(first_vehicle_arrival_seconds=100,
                                  all_vehicles_arrival_seconds=241),
            AC,
        )
        assert validate_success(resp2)["outcome"] == "FAIL"


class TestDrillRunwayHalfOpenAdjacency:
    def test_half_open_adjacency_allowed_straddle_rejected(self, api):
        """PRD §3.7: "The window uses half-open semantics: the interval
        includes `scheduled_start` and excludes `scheduled_end`. A new drill
        whose half-open window overlaps any other `SCHEDULED` drill on the
        same runway is rejected with `ERR_DRILL_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/ro_drill_runway_half_open_adjacency
        """
        setup_profile_only()
        # Drill 1: 10:00-11:00
        r1 = api.create_response_drill(
            create_response_drill_payload(
                runway_designator="09L",
                scheduled_start="2026-05-03T10:00:00Z",
                scheduled_end="2026-05-03T11:00:00Z",
            ),
            AC,
        )
        validate_success(r1, expected_status=201)
        # Drill 2: 11:00-12:00 — adjacency allowed under half-open
        r2 = api.create_response_drill(
            create_response_drill_payload(
                runway_designator="09L",
                scheduled_start="2026-05-03T11:00:00Z",
                scheduled_end="2026-05-03T12:00:00Z",
            ),
            AC,
        )
        d2 = validate_success(r2, expected_status=201)
        assert d2["status"] == "SCHEDULED"
        # Drill 3: 10:30-11:30 — straddles the boundary, rejected
        r3 = api.create_response_drill(
            create_response_drill_payload(
                runway_designator="09L",
                scheduled_start="2026-05-03T10:30:00Z",
                scheduled_end="2026-05-03T11:30:00Z",
            ),
            AC,
        )
        validate_error(r3, ApiErrorId.ERR_DRILL_WINDOW_OVERLAP)

    def test_different_runway_same_window_allowed(self, api):
        """PRD §3.7: "A new drill whose half-open window overlaps any other
        `SCHEDULED` drill on the same runway is rejected with
        `ERR_DRILL_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/ro_drill_runway_half_open_adjacency
        """
        setup_profile_only()
        r1 = api.create_response_drill(
            create_response_drill_payload(
                runway_designator="09L",
                scheduled_start="2026-05-03T10:00:00Z",
                scheduled_end="2026-05-03T11:00:00Z",
            ),
            AC,
        )
        validate_success(r1, expected_status=201)
        r2 = api.create_response_drill(
            create_response_drill_payload(
                runway_designator="27R",
                scheduled_start="2026-05-03T10:30:00Z",
                scheduled_end="2026-05-03T11:30:00Z",
            ),
            AC,
        )
        d = validate_success(r2, expected_status=201)
        assert d["runway_designator"] == "27R"


class TestDrillWindowInvalid:
    def test_drill_window_invalid_when_start_not_before_end(self, api):
        """PRD §3.7: "The `ArffChief` schedules a timed response drill by
        naming a `runway_designator` and a window with `scheduled_start`
        strictly before `scheduled_end`; a non-positive window is rejected
        with `ERR_DRILL_WINDOW_INVALID`."

        Design: Corner/validations/val_drill_window_invalid_when_start_not_before_end
        """
        setup_profile_only()
        resp = api.create_response_drill(
            create_response_drill_payload(
                runway_designator="09L",
                scheduled_start="2026-05-03T11:00:00Z",
                scheduled_end="2026-05-03T11:00:00Z",
            ),
            AC,
        )
        validate_error(resp, ApiErrorId.ERR_DRILL_WINDOW_INVALID)


class TestDrillWindowExecuteBounds:
    def test_execute_before_window_start_rejected(self, api):
        """PRD §3.7: "An attempt to execute before `scheduled_start` is
        rejected with `ERR_DRILL_WINDOW_INVALID`; an attempt after
        `scheduled_end` is rejected with `ERR_DRILL_WINDOW_EXPIRED`."

        Design: Corner/errors/err_operations_misc_error_battery
        """
        setup_compliant_index_c_airport()
        d = validate_success(
            api.create_response_drill(
                create_response_drill_payload(
                    runway_designator="09L",
                    scheduled_start="2026-05-03T10:00:00Z",
                    scheduled_end="2026-05-03T11:00:00Z",
                ),
                AC,
            ),
            expected_status=201,
        )
        # Clock still 2026-05-01 -> before window
        resp = api.execute_response_drill(
            d["id"],
            execute_drill_payload(first_vehicle_arrival_seconds=100,
                                  all_vehicles_arrival_seconds=200),
            AC,
        )
        validate_error(resp, ApiErrorId.ERR_DRILL_WINDOW_INVALID)

    def test_execute_after_window_end_rejected(self, api):
        """PRD §3.7: "An attempt to execute before `scheduled_start` is
        rejected with `ERR_DRILL_WINDOW_INVALID`; an attempt after
        `scheduled_end` is rejected with `ERR_DRILL_WINDOW_EXPIRED`."

        Design: Corner/errors/err_operations_misc_error_battery
        """
        setup_compliant_index_c_airport()
        d = validate_success(
            api.create_response_drill(
                create_response_drill_payload(
                    runway_designator="09L",
                    scheduled_start="2026-05-03T10:00:00Z",
                    scheduled_end="2026-05-03T11:00:00Z",
                ),
                AC,
            ),
            expected_status=201,
        )
        set_clock("2026-05-03T11:30:00Z")
        resp = api.execute_response_drill(
            d["id"],
            execute_drill_payload(first_vehicle_arrival_seconds=100,
                                  all_vehicles_arrival_seconds=200),
            AC,
        )
        validate_error(resp, ApiErrorId.ERR_DRILL_WINDOW_EXPIRED)


class TestDrillNotFoundBeatsState:
    def test_certify_unknown_drill_returns_404(self, api):
        """PRD §2.9: "The leftmost path `id` is resolved first; if it does
        not exist, the request is rejected with the corresponding
        `ERR_<RESOURCE>_NOT_FOUND` (HTTP 404) before any right-hand identifier
        is examined."

        Design: Corner/validations/val_priority_existence_beats_state
        """
        setup_profile_only()
        resp = api.certify_response_drill(NON_EXISTENT_UUID, AC)
        validate_error(resp, ApiErrorId.ERR_DRILL_NOT_FOUND)
