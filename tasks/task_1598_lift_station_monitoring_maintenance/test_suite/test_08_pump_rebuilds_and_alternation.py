"""Pump rebuild cycle (runtime reset semantics) and the alternation threshold."""
import pytest

from test_helpers import (
    ApiErrorId,
    accumulate_runtime,
    add_pump,
    add_reading,
    create_station,
    get_pump,
    open_rebuild,
    reset_clock,
    setup_station_with_pumps,
    validate_error,
    validate_success,
)


class TestPumpRebuildCycle:
    def test_rebuild_cycle_resets_since_rebuild_but_not_cumulative(
        self, api, maintenance_planner_headers
    ):
        """PRD §3.4: "Completion — again requiring the pump in `REBUILD` —
        stamps the rebuild's `completed_at`, flips the pump `REBUILD →
        IN_SERVICE`, resets the pump's `runtime_since_rebuild_hours` to 0, and
        increments its `rebuild_count`."
        PRD §3.2: "Each accepted reading adds its `run_hours_delta` to both
        `cumulative_runtime_hours` and `runtime_since_rebuild_hours`; the latter
        resets to 0 only when a pump returns from rebuild."
        PRD §3.4: "Starting work requires the pump to actually be in `REBUILD`
        and snapshots the pump's current `runtime_since_rebuild_hours` into the
        rebuild's `pre_rebuild_runtime_hours`."

        Design: Difficulty/non_linear_state_machine/pump_rebuild_cycle
        """
        reset_clock()
        station, pumps = setup_station_with_pumps(
            ratings=(200, 200, 200), design_capacity_gpm=600,
        )
        p1 = pumps[0]
        accumulate_runtime(p1["id"], 500.0)
        pump_before = get_pump(p1["id"])
        assert pump_before["cumulative_runtime_hours"] == pytest.approx(500.0)
        assert pump_before["runtime_since_rebuild_hours"] == pytest.approx(500.0)

        rebuild = open_rebuild(p1["id"], work_order_ref="WO-1",
                               started_at="2026-08-01T21:00:00Z", cost_usd=15000)
        assert get_pump(p1["id"])["status"] == "REBUILD"
        res = api.start_pump_rebuild(rebuild["id"], maintenance_planner_headers)
        started = validate_success(res, 200)
        assert started["status"] == "IN_PROGRESS"
        assert started["pre_rebuild_runtime_hours"] == pytest.approx(500.0), (
            "snapshot taken at the IN_PROGRESS transition"
        )
        res = api.complete_pump_rebuild(rebuild["id"], maintenance_planner_headers)
        completed = validate_success(res, 200)
        assert completed["status"] == "COMPLETED"
        assert completed["completed_at"] is not None

        pump_after = get_pump(p1["id"])
        assert pump_after["status"] == "IN_SERVICE", "cycle REBUILD -> IN_SERVICE completed"
        assert pump_after["runtime_since_rebuild_hours"] == pytest.approx(0.0)
        assert pump_after["cumulative_runtime_hours"] == pytest.approx(500.0), (
            "lifetime runtime is not reset by a rebuild"
        )
        assert pump_after["rebuild_count"] == 1

    def test_rebuild_cancel_slides_pump_out_of_service(self, api, maintenance_planner_headers):
        """PRD §3.4: "Cancellation is possible from `OPEN` (by a
        `MaintenancePlanner`) or `IN_PROGRESS` (by an `OperationsSupervisor`);
        either way the pump slides `REBUILD → OUT_OF_SERVICE` rather than
        returning to duty. `COMPLETED` and `CANCELLED` are terminal."

        Design: Difficulty/non_linear_state_machine/pump_rebuild_cycle
        """
        reset_clock()
        station, pumps = setup_station_with_pumps(
            ratings=(200, 200, 200), design_capacity_gpm=600,
        )
        rebuild = open_rebuild(pumps[0]["id"], work_order_ref="WO-2")
        assert get_pump(pumps[0]["id"])["status"] == "REBUILD"
        res = api.cancel_pump_rebuild(rebuild["id"], maintenance_planner_headers)
        cancelled = validate_success(res, 200)
        assert cancelled["status"] == "CANCELLED"
        assert get_pump(pumps[0]["id"])["status"] == "OUT_OF_SERVICE"


class TestPumpAlternation:
    def test_no_swap_below_alternation_threshold(self, api, operations_supervisor_headers):
        """PRD §3.5: "The swap executes only when the candidate's
        `runtime_since_rebuild_hours` is greater than or equal to the current
        lead's `runtime_since_rebuild_hours` plus the 24.0-hour alternation
        threshold, with hour comparisons carried at two-decimal precision. When
        the threshold is met the two pumps exchange `position_index` values, the
        new lead's `last_alternation_at` is stamped with the current time, and
        the alternated pump is returned; when it is not, nothing changes."

        Design: Difficulty/resource_temporal_overlap/pump_alternation_runtime_threshold
        """
        reset_clock()
        station, pumps = setup_station_with_pumps(ratings=(150, 150))
        p1, p2 = pumps
        add_reading(p1["id"], "2026-08-01T00:00:00Z", 10.0, starts_count=5)
        add_reading(p2["id"], "2026-08-01T00:00:00Z", 10.0, starts_count=5)
        res = api.alternate_pumps(station["id"], operations_supervisor_headers)
        validate_success(res, 200)
        assert get_pump(p1["id"])["position_index"] == 1, (
            "runtime difference 0 < 24h threshold — nothing changes"
        )
        assert get_pump(p2["id"])["position_index"] == 2

    def test_swap_at_exactly_alternation_threshold(self, api, operations_supervisor_headers):
        """PRD §3.5: "The swap executes only when the candidate's
        `runtime_since_rebuild_hours` is greater than or equal to the current
        lead's `runtime_since_rebuild_hours` plus the 24.0-hour alternation
        threshold, with hour comparisons carried at two-decimal precision. When
        the threshold is met the two pumps exchange `position_index` values, the
        new lead's `last_alternation_at` is stamped with the current time, and
        the alternated pump is returned; when it is not, nothing changes."
        PRD §3.5: "Otherwise the server identifies the current lead (lowest
        `position_index` among `IN_SERVICE` pumps) and the candidate successor:
        among the other `IN_SERVICE` pumps, the one with the lowest
        `runtime_since_rebuild_hours`, ties broken by earlier `created_at`."

        Design: Difficulty/resource_temporal_overlap/pump_alternation_runtime_threshold
        """
        reset_clock()
        station, pumps = setup_station_with_pumps(ratings=(150, 150))
        p1, p2 = pumps
        add_reading(p1["id"], "2026-08-01T00:00:00Z", 10.0)
        add_reading(p2["id"], "2026-08-01T00:00:00Z", 24.0)
        add_reading(p2["id"], "2026-08-01T01:00:00Z", 10.0)
        res = api.alternate_pumps(station["id"], operations_supervisor_headers)
        validate_success(res, 200)
        p1_after = get_pump(p1["id"])
        p2_after = get_pump(p2["id"])
        assert p2_after["position_index"] == 1, (
            "candidate at exactly lead+24.0h swaps into the lead slot"
        )
        assert p1_after["position_index"] == 2
        assert p2_after["last_alternation_at"] is not None

    def test_error_no_pumps_to_alternate_on_single_pump(self, api, operations_supervisor_headers):
        """PRD §3.5: "The rule considers only the station's `IN_SERVICE` pumps;
        if fewer than two are in service, no alternation is possible and the
        request is rejected with `ERR_NO_PUMPS_TO_ALTERNATE` (HTTP 422)."

        Design: Corner/errors/error_no_pumps_to_alternate_on_single_pump
        """
        reset_clock()
        station = create_station(design_capacity_gpm=100, pump_count=2)
        add_pump(station["id"], 1, 100)
        res = api.alternate_pumps(station["id"], operations_supervisor_headers)
        validate_error(res, ApiErrorId.ERR_NO_PUMPS_TO_ALTERNATE)
