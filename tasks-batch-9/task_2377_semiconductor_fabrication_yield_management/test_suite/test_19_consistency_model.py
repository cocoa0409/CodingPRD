"""One act, every consequence, all inside the same request.

The scenario contains an excursion and then proves the cascade is already visible
to the very next read and already enforced by the very next write.
"""

from test_helpers import (
    build_line,
    fab_planner_headers,
    make_operator_headers,
    metrology_step_spec,
    quality_manager_headers,
    raise_spc_excursion,
)
from test_helpers.api_errors import ERR_SPC_CHART_SUSPENDED
from test_helpers.assertions import assert_fields, assert_lot_state
from test_helpers.factories import contain_payload, measurement_payload
from prd_bench_local_runner.testing.validators import validate_error, validate_success


class TestContainmentCascadeVisibility:
    def test_containment_publishes_every_effect_before_it_answers(self, fab):
        """The chart, the lot and both listings have all moved by the time 200 returns.

        PRD: "A single act on the line frequently has consequences on other rows,
        and the server applies all of them synchronously within the same request."

        PRD: "At `SPC_CHART` scope, the chart is driven `MONITORING → SUSPENDED`,
        and every lot holding an open run on that chart's `step_id` whose
        `flow_state` is `RELEASED` or `IN_PROCESS` is raised from `NONE` to
        `SPC_HOLD` with its `hold_excursion_id` set to this excursion."

        PRD: "And the chart's `status` must be `MONITORING`; a chart frozen by
        containment rejects the reading outright with `ERR_SPC_CHART_SUSPENDED` and
        therefore contributes no state to the run rule."

        Design: Corner/consistency_model/containment_publishes_every_cascade_effect_within_the_same_response
        """
        env = build_line(fab, metrology_step_spec())
        raised = raise_spc_excursion(fab, env, 112.0, step_ix=0, lot_ix=0)
        assert raised.measurement["classification"] == "OUT_OF_SPEC"
        assert raised.excursion["status"] == "OPEN"

        response = fab.client.contain_excursion(
            raised.excursion["id"],
            contain_payload("SPC_CHART"),
            quality_manager_headers(),
        )

        contained = validate_success(response, 200)
        assert_fields(
            contained,
            status="CONTAINED",
            severity_variant="FINAL",
            containment_scope="SPC_CHART",
        )
        assert fab.read_chart(env.charts[0]["id"])["status"] == "SUSPENDED"
        held = fab.read_lot(env.lots[0]["id"])
        assert_lot_state(held, hold_state="SPC_HOLD")
        assert held["hold_excursion_id"] == raised.excursion["id"]
        assert fab.count(
            fab.client.list_lots(fab_planner_headers(), {"hold_state": "SPC_HOLD"})
        ) == 1
        assert fab.count(
            fab.client.list_excursions(
                quality_manager_headers(),
                {"spc_chart_id": env.charts[0]["id"], "status": "CONTAINED"},
            )
        ) == 1

        refused = fab.client.create_measurement(
            measurement_payload(raised.run["id"], env.charts[0]["id"], 100.0),
            make_operator_headers(env.operators[0]["id"]),
        )

        body = validate_error(refused, ERR_SPC_CHART_SUSPENDED, 409)
        assert body["error_id"] == ERR_SPC_CHART_SUSPENDED
