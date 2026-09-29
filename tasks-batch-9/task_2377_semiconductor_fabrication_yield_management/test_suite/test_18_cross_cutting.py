"""Layers that cross the whole line: parent-lot concurrency and chart drift.

Both scenarios need several prior writes to be in the right order before the act
under test can mean anything at all.
"""

from test_helpers import (
    LotSpec,
    build_line,
    fab_planner_headers,
    make_operator_headers,
    metrology_step_spec,
    open_run,
    process_engineer_headers,
    single_step_spec,
)
from test_helpers.api_errors import ERR_STALE_LOT_VERSION
from test_helpers.assertions import (
    assert_fields,
    assert_hours,
    assert_lot_state,
    assert_nulls,
    assert_ratio,
)
from test_helpers.factories import measurement_payload, split_payload
from prd_bench_local_runner.testing.validators import validate_error, validate_success


# --------------------------------------------------------------------------
# Optimistic concurrency on the parent of a split
# --------------------------------------------------------------------------


class TestParentLotConcurrency:
    def test_a_split_carrying_the_pre_release_parent_version_is_refused(self, fab):
        """Release already moved the parent's version, so the captured one is stale.

        PRD: "Creating an engineering split requires `expected_lot_version`,
        carrying the client's last observed `version` of the parent `Lot`."

        PRD: "A mismatch with the parent lot's current `version` is rejected with
        `ERR_STALE_LOT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/a_split_carrying_the_pre_release_lot_version_returns_stale_lot_version
        """
        env = build_line(
            fab,
            single_step_spec(
                planned_wafer_starts=30,
                capacity_budget_hours=200.0,
                lots=[LotSpec("LOT-001", 25, release=False)],
            ),
        )
        version_at_creation = env.lots[0]["version"]
        released = fab.release_lot(env.lots[0]["id"], env.plan["id"])
        assert_lot_state(released, flow_state="RELEASED")
        assert released["version"] != version_at_creation

        response = fab.client.split_lot(
            released["id"],
            split_payload(version_at_creation, 10, "LOT-001-S1"),
            process_engineer_headers(),
        )

        body = validate_error(response, ERR_STALE_LOT_VERSION, 412)
        assert body["error_id"] == ERR_STALE_LOT_VERSION
        untouched = fab.read_lot(released["id"])
        assert untouched["wafer_count"] == 25
        assert untouched["version"] == released["version"]
        assert fab.count(
            fab.client.list_lots(
                fab_planner_headers(), {"parent_lot_id": released["id"]}
            )
        ) == 0


# --------------------------------------------------------------------------
# The Western Electric run rule
# --------------------------------------------------------------------------


class TestRunRuleDrift:
    def test_the_fourth_consecutive_one_sigma_point_opens_an_excursion(self, fab):
        """Four readings 1.5 sigma above centre never breach a limit, yet still trip.

        PRD: "The measurement's `run_rule_triggered` is true when the resulting
        `consecutive_same_side_count` is 4 or more, meaning four consecutive points
        on the same side of the centre line, each at least one `sigma` away from
        it."

        PRD: "When the `classification` is `OUT_OF_CONTROL` or `OUT_OF_SPEC`, or
        `run_rule_triggered` is true, the chart's `violation_count` increments by 1
        and an **excursion** is opened: `source_type` `SPC`, `spc_chart_id`
        pointing at the chart, `lot_id` copied from the run's `lot_id`,
        `trigger_value` set to the reading rounded to 4 decimal places, and the
        measurement's own `excursion_id` set to the new excursion."

        Design: Corner/cross_cutting_complexity_layers/the_fourth_consecutive_one_sigma_point_trips_the_western_electric_run_rule
        """
        env = build_line(fab, metrology_step_spec())
        run = open_run(fab, env, step_ix=0, lot_ix=0)
        chart_id = env.charts[0]["id"]
        operator_id = env.operators[0]["id"]

        first = fab.measure(run["id"], chart_id, 103.0, operator_id)
        assert first["classification"] == "IN_CONTROL"
        # Three units above a 100.00 centre line on a 2.00 sigma.
        assert_ratio(first["deviation_sigma"], 1.5000, "deviation_sigma")
        assert_nulls(first, "excursion_id")
        second = fab.measure(run["id"], chart_id, 103.0, operator_id)
        assert second["classification"] == "IN_CONTROL"
        assert second["run_rule_triggered"] is False
        third = fab.measure(run["id"], chart_id, 103.0, operator_id)
        assert third["classification"] == "IN_CONTROL"
        assert third["run_rule_triggered"] is False
        assert_fields(
            fab.read_chart(chart_id),
            consecutive_same_side_count=3,
            last_side="ABOVE",
            violation_count=0,
            status="MONITORING",
        )

        response = fab.client.create_measurement(
            measurement_payload(run["id"], chart_id, 103.0),
            make_operator_headers(operator_id),
        )

        fourth = validate_success(response, 201)
        assert fourth["classification"] == "IN_CONTROL"
        assert fourth["run_rule_triggered"] is True
        assert fourth["excursion_id"] is not None
        assert_fields(
            fab.read_chart(chart_id),
            consecutive_same_side_count=4,
            last_side="ABOVE",
            violation_count=1,
            status="MONITORING",
        )
        excursion = fab.read_excursion(fourth["excursion_id"])
        assert_fields(
            excursion,
            source_type="SPC",
            severity_band="LOW",
            severity_variant="PROVISIONAL",
            affected_lot_count=1,
        )
        assert_ratio(excursion["trigger_value"], 103.0000, "trigger_value")
        # 60.0 times 3.00 / 10.00 of the upper spec span, plus 3.0 for one lot.
        assert_hours(excursion["severity_score"], 21.00, "severity_score")
        assert_lot_state(fab.read_lot(env.lots[0]["id"]), hold_state="NONE")
