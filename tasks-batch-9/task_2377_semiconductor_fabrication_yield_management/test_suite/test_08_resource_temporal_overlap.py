"""Two ways of holding a resource over time, with opposite interval conventions.

Chamber occupancy runs from track-in to an unscheduled track-out; the post-maintenance
purge window is a closed interval with a published upper bound. Each scenario probes
the moment the resource becomes usable again.
"""

from test_helpers import (
    ChamberSpec,
    EquipmentSpec,
    LotSpec,
    build_line,
    make_operator_headers,
    two_recipe_line_spec,
)
from test_helpers.api_errors import ERR_NO_QUALIFIED_CHAMBER, ERR_PM_PURGE_ACTIVE
from test_helpers.assertions import (
    assert_fields,
    assert_hours,
    assert_lot_state,
    assert_timestamp_equals,
)
from test_helpers.factories import step_run_payload
from prd_bench_local_runner.testing.validators import validate_error


# --------------------------------------------------------------------------
# Chamber occupancy: open-ended until an explicit track-out
# --------------------------------------------------------------------------


def _one_litho_chamber_two_lots(fab):
    """The only litho chamber in the fab, with two released lots queued for it."""
    spec = two_recipe_line_spec(
        equipments=[EquipmentSpec("LITHO-1", "LITHO", 168.0, 0.0, 0.0)],
        chambers=[ChamberSpec("CH_L1", equipment_ix=0, recipe_ix=0)],
    )
    return build_line(fab, spec)


class TestChamberOccupancyInterval:
    def test_an_occupied_chamber_is_excluded_for_as_long_as_the_run_is_open(self, fab):
        """The occupancy has no scheduled end, so the second lot finds an empty pool.

        PRD: "Chambers on tools in `PM` or `DOWN` are excluded by that filter, as
        are chambers already `OCCUPIED` by an open run."

        Design: Difficulty/resource_temporal_overlap/chamber_occupancy_is_open_ended_until_track_out
        """
        env = _one_litho_chamber_two_lots(fab)
        operator_id = env.operators[0]["id"]

        first_run = fab.track_in(
            env.lots[0]["id"], env.steps[0]["id"], operator_id
        )

        assert first_run["chamber_id"] == env.chambers[0]["id"]
        assert_timestamp_equals(
            first_run["tracked_in_at"], "2026-08-01T00:00:00Z", "tracked_in_at"
        )
        assert fab.read_chamber(env.chambers[0]["id"])["occupancy_state"] == "OCCUPIED"
        assert_hours(
            fab.read_equipment(env.equipments[0]["id"])["available_capacity_hours"],
            718.00,
            "available_capacity_hours",
        )

        response = fab.client.create_step_run(
            step_run_payload(env.lots[1]["id"], env.steps[0]["id"], operator_id),
            make_operator_headers(operator_id),
        )

        validate_error(response, ERR_NO_QUALIFIED_CHAMBER, 409)
        assert_lot_state(fab.read_lot(env.lots[1]["id"]), flow_state="RELEASED")

    def test_the_track_out_closes_the_interval_and_frees_the_same_chamber(self, fab):
        """The identical call succeeds the instant the first run is closed.

        PRD: "On success the run is driven `OPEN → COMPLETED`, `tracked_out_at`
        is set to the current logical instant, and `actual_hours` is the interval
        from `tracked_in_at` to `tracked_out_at` expressed in hours and rounded
        to 2 decimal places."

        Design: Difficulty/resource_temporal_overlap/chamber_occupancy_is_open_ended_until_track_out
        """
        env = _one_litho_chamber_two_lots(fab)
        operator_id = env.operators[0]["id"]
        first_run = fab.track_in(env.lots[0]["id"], env.steps[0]["id"], operator_id)
        fab.client.create_step_run(
            step_run_payload(env.lots[1]["id"], env.steps[0]["id"], operator_id),
            make_operator_headers(operator_id),
        )

        fab.set_clock("2026-08-01T02:00:00Z")
        closed = fab.track_out(first_run["id"], operator_id)

        assert closed["status"] == "COMPLETED"
        assert_timestamp_equals(
            closed["tracked_out_at"], "2026-08-01T02:00:00Z", "tracked_out_at"
        )
        assert_hours(closed["actual_hours"], 2.00, "actual_hours")
        assert fab.read_chamber(env.chambers[0]["id"])["occupancy_state"] == "FREE"
        freed_tool = fab.read_equipment(env.equipments[0]["id"])
        assert_hours(
            freed_tool["available_capacity_hours"], 718.00, "available_capacity_hours"
        )
        assert_hours(freed_tool["hours_since_pm"], 2.0, "hours_since_pm")

        second_run = fab.track_in(env.lots[1]["id"], env.steps[0]["id"], operator_id)

        assert_fields(second_run, status="OPEN", chamber_id=env.chambers[0]["id"])
        assert_timestamp_equals(
            second_run["tracked_in_at"], "2026-08-01T02:00:00Z", "tracked_in_at"
        )
        assert_hours(
            fab.read_equipment(env.equipments[0]["id"])["available_capacity_hours"],
            716.00,
            "available_capacity_hours",
        )
        assert_lot_state(fab.read_lot(env.lots[0]["id"]), current_step_seq=10)
        assert_lot_state(fab.read_lot(env.lots[1]["id"]), flow_state="IN_PROCESS")


# --------------------------------------------------------------------------
# The purge window: a closed interval with a published upper bound
# --------------------------------------------------------------------------


def _tool_inside_its_purge_window(fab):
    """A tool that finished maintenance at 2026-08-02 with a 24-hour purge buffer."""
    env = build_line(fab, two_recipe_line_spec(lots=[LotSpec("LOT-001", 3, "STANDARD")]))
    fab.set_clock("2026-08-02T00:00:00Z")
    fab.pm_start(env.equipments[0]["id"], "Scheduled 168-hour PM")
    env.tool = fab.pm_complete(env.equipments[0]["id"])
    return env


class TestPurgeWindowUpperBound:
    def test_a_track_in_exactly_on_the_upper_bound_is_still_refused(self, fab):
        """The window includes its own end instant, so 2026-08-03T00:00:00Z fails.

        PRD: "During the purge window no run may open on any of the tool's
        chambers: the interval is closed, so a track-in at exactly `purge_until`
        is still rejected with `ERR_PM_PURGE_ACTIVE`, and only a strictly later
        instant is admitted."

        Design: Difficulty/resource_temporal_overlap/pm_purge_window_is_closed_at_its_upper_bound
        """
        env = _tool_inside_its_purge_window(fab)
        operator_id = env.operators[0]["id"]

        assert env.tool["state"] == "IDLE"
        assert_timestamp_equals(
            env.tool["purge_until"], "2026-08-03T00:00:00Z", "purge_until"
        )
        assert_hours(
            env.tool["available_capacity_hours"], 720.00, "available_capacity_hours"
        )

        fab.set_clock("2026-08-03T00:00:00Z")
        response = fab.client.create_step_run(
            step_run_payload(env.lots[0]["id"], env.steps[0]["id"], operator_id),
            make_operator_headers(operator_id),
        )

        validate_error(response, ERR_PM_PURGE_ACTIVE, 409)
        assert fab.count(
            fab.client.list_step_runs(
                make_operator_headers(operator_id),
                {"lot_id": env.lots[0]["id"], "status": "OPEN"},
            )
        ) == 0
        assert_lot_state(fab.read_lot(env.lots[0]["id"]), flow_state="RELEASED")

    def test_one_second_past_the_bound_the_same_call_opens_a_run(self, fab):
        """Only a strictly later instant is admitted, and it reserves the step's hours.

        PRD: "On success a run is created in `OPEN` `status` with `tracked_in_at`
        at the current logical instant, `tracked_out_at` and `actual_hours` null,
        and `reserved_hours` captured from the step's `standard_hours`."

        Design: Difficulty/resource_temporal_overlap/pm_purge_window_is_closed_at_its_upper_bound
        """
        env = _tool_inside_its_purge_window(fab)
        operator_id = env.operators[0]["id"]

        fab.set_clock("2026-08-03T00:00:00Z")
        fab.client.create_step_run(
            step_run_payload(env.lots[0]["id"], env.steps[0]["id"], operator_id),
            make_operator_headers(operator_id),
        )

        fab.set_clock("2026-08-03T00:00:01Z")
        run = fab.track_in(env.lots[0]["id"], env.steps[0]["id"], operator_id)

        assert_fields(run, status="OPEN", chamber_id=env.chambers[0]["id"])
        assert_timestamp_equals(
            run["tracked_in_at"], "2026-08-03T00:00:01Z", "tracked_in_at"
        )
        assert_hours(run["reserved_hours"], 2.00, "reserved_hours")

        tool = fab.read_equipment(env.equipments[0]["id"])
        assert tool["state"] == "PRODUCTIVE"
        assert_hours(
            tool["available_capacity_hours"], 718.00, "available_capacity_hours"
        )
        assert_lot_state(fab.read_lot(env.lots[0]["id"]), flow_state="IN_PROCESS")
