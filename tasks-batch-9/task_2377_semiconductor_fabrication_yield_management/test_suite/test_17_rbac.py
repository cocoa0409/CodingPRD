"""Who may call what, and the two decisions that need two different people.

The refusals are arranged so role authorisation is the only check that can fail
first; the two permissive scenarios prove a shared endpoint really is shared.
"""

from test_helpers import (
    LotSpec,
    UNKNOWN_CR_ID_FOR_RBAC,
    UNKNOWN_EXCURSION_ID_FOR_RBAC,
    UNKNOWN_LOT_ID_FOR_RBAC,
    USER_QUALITY_MANAGER,
    build_line,
    equipment_engineer_headers,
    fab_planner_headers,
    metrology_step_spec,
    operator_headers_opaque,
    process_engineer_headers,
    quality_manager_headers,
    raise_spc_excursion,
    single_step_spec,
    yield_engineer_headers,
)
from test_helpers.api_errors import ERR_SOD_SELF_DISPOSITION, ERR_UNAUTHORIZED
from test_helpers.assertions import (
    assert_common_fields,
    assert_envelope,
    assert_fields,
    assert_hours,
    assert_lot_state,
    assert_nulls,
)
from test_helpers.factories import (
    approve_payload,
    contain_payload,
    die_sort_payload,
    disposition_payload,
    recipe_payload,
    spc_chart_payload,
    wafer_result,
)
from prd_bench_local_runner.testing.validators import validate_error, validate_success


# --------------------------------------------------------------------------
# Refusals: the role is well-formed but not on the endpoint's roster
# --------------------------------------------------------------------------


class TestRoleRefusals:
    def test_an_operator_may_not_author_a_recipe(self, fab):
        """Recipe authorship belongs to process engineering alone.

        PRD: "A request whose role is well-formed but is not listed among the
        authorised roles for the endpoint being called is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/an_operator_cannot_author_a_recipe
        """
        response = fab.client.create_recipe(
            recipe_payload("LITHO-200", "LITHO", 50.0, drop=["qual_expiry_days"]),
            operator_headers_opaque(),
        )

        body = validate_error(response, ERR_UNAUTHORIZED, 403)
        assert body["error_id"] == ERR_UNAUTHORIZED
        assert fab.count(fab.client.list_recipes(process_engineer_headers())) == 0

    def test_a_fab_planner_may_not_approve_a_change_notice(self, fab):
        """Role authorisation is checked before the notice is even resolved.

        PRD: "| POST | `/fab/change-requests/{id}/approve` | Approve a submitted
        notice, pinning the recipe revision | QualityManager |"

        PRD: "A request whose role is well-formed but is not listed among the
        authorised roles for the endpoint being called is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/a_fab_planner_cannot_approve_a_change_request
        """
        recipe = fab.recipe("LITHO-200", "LITHO", 50.0, 100)

        response = fab.client.approve_change_request(
            UNKNOWN_CR_ID_FOR_RBAC,
            approve_payload(recipe["version"]),
            fab_planner_headers(),
        )

        body = validate_error(response, ERR_UNAUTHORIZED, 403)
        assert body["error_id"] == ERR_UNAUTHORIZED

    def test_a_yield_engineer_may_not_contain_an_excursion(self, fab):
        """Containment is the quality manager's call, so 403 arrives before 404.

        PRD: "| POST | `/fab/excursions/{id}/contain` | Contain an SPC- or
        die-sort-sourced excursion at a chosen blast radius | QualityManager |"

        PRD: "A request whose role is well-formed but is not listed among the
        authorised roles for the endpoint being called is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/a_yield_engineer_cannot_contain_an_excursion
        """
        response = fab.client.contain_excursion(
            UNKNOWN_EXCURSION_ID_FOR_RBAC,
            contain_payload("SPC_CHART"),
            yield_engineer_headers(),
        )

        body = validate_error(response, ERR_UNAUTHORIZED, 403)
        assert body["error_id"] == ERR_UNAUTHORIZED

    def test_a_process_engineer_may_not_commit_a_wafer_start_plan(self, fab):
        """Pricing is the planner's act, and the refused plan is left unpriced.

        PRD: "| POST | `/fab/wafer-start-plans/{id}/commit` | Commit a draft plan
        through the utilisation tier ladder | FabPlanner |"

        PRD: "A request whose role is well-formed but is not listed among the
        authorised roles for the endpoint being called is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/a_process_engineer_cannot_commit_a_wafer_start_plan
        """
        env = build_line(fab, single_step_spec(commit_plan=False, lots=[]))
        assert env.plan["status"] == "DRAFT"

        response = fab.client.commit_plan(env.plan["id"], process_engineer_headers())

        body = validate_error(response, ERR_UNAUTHORIZED, 403)
        assert body["error_id"] == ERR_UNAUTHORIZED
        stored = fab.read_plan(env.plan["id"])
        assert stored["status"] == "DRAFT"
        assert_hours(stored["committed_hours"], 0.0, "committed_hours")

    def test_an_equipment_engineer_may_not_file_die_sort_results(self, fab):
        """Sort data belongs to yield engineering, and nothing is recorded.

        PRD: "| POST | `/fab/die-sort-runs` | Record wafer-map sort results for a
        lot at sort | YieldEngineer |"

        PRD: "A request whose role is well-formed but is not listed among the
        authorised roles for the endpoint being called is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/an_equipment_engineer_cannot_file_die_sort_results
        """
        response = fab.client.create_die_sort_run(
            die_sort_payload(
                UNKNOWN_LOT_ID_FOR_RBAC,
                [wafer_result(1, 100, 90, edge_ring_fails=10)],
                gross_die_per_wafer=100,
                baseline_yield=0.92,
            ),
            equipment_engineer_headers(),
        )

        body = validate_error(response, ERR_UNAUTHORIZED, 403)
        assert body["error_id"] == ERR_UNAUTHORIZED
        assert fab.count(
            fab.client.list_die_sort_runs(yield_engineer_headers())
        ) == 0


# --------------------------------------------------------------------------
# Endpoints deliberately open to more than one role
# --------------------------------------------------------------------------


class TestSharedEndpoints:
    def test_a_quality_manager_may_define_a_chart_on_an_engineered_step(self, fab):
        """The chart endpoint names two roles, so quality may author one too.

        PRD: "An SPC chart is attached to a metrology-bearing step by a
        `ProcessEngineer` or a `QualityManager`, naming the `step_id` it monitors,
        a `param_name` label, a centre line `target`, a process standard deviation
        `sigma` greater than zero, and four limits: `usl` and `lsl` as the upper
        and lower specification limits, and `ucl` and `lcl` as the upper and lower
        control limits, ordered so that `lsl` is below `lcl`, `lcl` is below
        `target`, `target` is below `ucl`, and `ucl` is below `usl`."

        Design: Corner/rbac/chart_definition_is_shared_between_process_engineering_and_quality
        """
        env = build_line(fab, metrology_step_spec(charts=[], lots=[]))

        response = fab.client.create_spc_chart(
            spc_chart_payload(
                env.steps[0]["id"], "CD", 100.0, 2.0, 110.0, 90.0, 106.0, 94.0
            ),
            quality_manager_headers(),
        )

        chart = validate_success(response, 201)
        assert_envelope(response.json(), "object")
        assert_fields(
            chart,
            status="MONITORING",
            violation_count=0,
            last_side="NONE",
            consecutive_same_side_count=0,
            step_id=env.steps[0]["id"],
        )
        assert_common_fields(chart, expected_version=1)

    def test_an_operator_may_read_the_lot_roster(self, fab):
        """The lot listing is open to all six roles, operators included.

        PRD: "| GET | `/fab/lots` | List lots, filterable by plan, flow, parent
        lot, holding excursion, hold state, flow state and priority | All roles |"

        PRD: "Six roles exist, spelled exactly as follows: `ProcessEngineer`,
        `QualityManager`, `EquipmentEngineer`, `FabPlanner`, `YieldEngineer`, and
        `Operator`."

        Design: Corner/rbac/every_role_including_operators_can_read_the_lot_roster
        """
        env = build_line(
            fab, single_step_spec(lots=[LotSpec("LOT-001", 3, release=False)])
        )

        response = fab.client.list_lots(
            operator_headers_opaque(), {"plan_id": env.plan["id"]}
        )

        rows = validate_success(response, 200)
        body = response.json()
        assert_envelope(body, "array")
        assert body["meta"]["total_count"] == 1
        assert rows[0]["id"] == env.lots[0]["id"]


# --------------------------------------------------------------------------
# Segregation of duties across containment and disposition
# --------------------------------------------------------------------------


class TestSegregationOfDuties:
    def test_the_containing_manager_may_not_also_disposition(self, fab):
        """The same X-User-ID that fixed the blast radius cannot decide the material.

        PRD: "Symmetrically, an excursion records the engineer who contained it in
        `contained_by_user_id`, and a disposition whose `X-User-ID` equals that
        value is rejected with `ERR_SOD_SELF_DISPOSITION` (HTTP 409)."

        Design: Corner/rbac/the_manager_who_contained_the_excursion_cannot_also_disposition_it
        """
        env = build_line(fab, metrology_step_spec())
        raised = raise_spc_excursion(fab, env, 112.0, step_ix=0, lot_ix=0)
        assert raised.measurement["classification"] == "OUT_OF_SPEC"

        contained = fab.contain(
            raised.excursion["id"], "SPC_CHART", user_id=USER_QUALITY_MANAGER
        )
        assert contained["status"] == "CONTAINED"
        assert contained["contained_by_user_id"] == USER_QUALITY_MANAGER

        response = fab.client.disposition_excursion(
            raised.excursion["id"],
            disposition_payload("CONTINUE", "Looks like a metrology artefact"),
            quality_manager_headers(USER_QUALITY_MANAGER),
        )

        body = validate_error(response, ERR_SOD_SELF_DISPOSITION, 409)
        assert body["error_id"] == ERR_SOD_SELF_DISPOSITION
        stored = fab.read_excursion(raised.excursion["id"])
        assert_fields(stored, status="CONTAINED", disposition="NONE")
        assert_nulls(stored, "dispositioned_by_user_id")
        assert fab.read_chart(env.charts[0]["id"])["status"] == "SUSPENDED"
        assert_lot_state(fab.read_lot(env.lots[0]["id"]), hold_state="SPC_HOLD")
