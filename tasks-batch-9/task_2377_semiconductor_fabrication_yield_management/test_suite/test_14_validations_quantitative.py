"""Refusals in the numbers: plan ledgers, wafer conservation, rework budget and sort.

Each scenario drives the line to the exact state where one quantitative rule bites,
fires the request that breaks it, and then proves the ledgers did not move.
"""

from test_helpers import (
    ChartSpec,
    LotSpec,
    StepSpec,
    advance_to_at_sort,
    build_line,
    complete_step,
    fab_planner_headers,
    process_engineer_headers,
    raise_spc_excursion,
    single_step_spec,
    sorted_run,
    yield_engineer_headers,
)
from test_helpers.api_errors import (
    ERR_CAPACITY_BUDGET_EXCEEDED,
    ERR_INVALID_SPLIT_QUANTITY,
    ERR_LOT_INVALID_STATE,
    ERR_NOT_A_SPLIT_LOT,
    ERR_PLAN_STARTS_EXCEEDED,
    ERR_PRODUCT_FAMILY_MISMATCH,
    ERR_REWORK_LIMIT_EXCEEDED,
    ERR_REWORK_TARGET_NOT_SET,
    ERR_SORT_RUN_ALREADY_BINNED,
    ERR_WAFER_RESULT_INCONSISTENT,
)
from test_helpers.assertions import (
    assert_fields,
    assert_hours,
    assert_lot_state,
    assert_nulls,
    assert_ratio,
)
from test_helpers.factories import (
    bin_payload,
    die_sort_payload,
    plan_payload,
    release_lot_payload,
    split_payload,
    wafer_result,
)
from prd_bench_local_runner.testing.validators import validate_error


# --------------------------------------------------------------------------
# Planning: family agreement, the budget and the wafer-start authorisation
# --------------------------------------------------------------------------


class TestPlanAdmissibility:
    def test_a_plan_must_name_the_flows_own_product_family(self, fab):
        """The flow runs LOGIC_N5, so a memory plan cannot be drafted against it.

        PRD: "A `FabPlanner` drafts a weekly plan naming the `flow_id` of a
        `RELEASED` flow — a flow that is `DRAFT` or `OBSOLETE` is rejected with
        `ERR_FLOW_NOT_RELEASED` — plus the `product_family` being planned, which
        must equal the flow's own `product_family` or the request is rejected with
        `ERR_PRODUCT_FAMILY_MISMATCH`; a `week_start_date` giving the first instant
        of the planning week in ISO 8601 UTC; `planned_wafer_starts`, at least 1,
        being the wafers the plan authorises for release during the week;
        `capacity_budget_hours`, greater than zero, being the fab capacity
        allocated to the plan; and `cycle_time_target_days`, greater than zero, the
        target days from lot release to sort."

        Design: Corner/validations/plan_for_a_different_product_family_returns_product_family_mismatch
        """
        env = build_line(fab, single_step_spec(make_plan=False))
        assert_fields(env.flow, product_family="LOGIC_N5", status="RELEASED")

        response = fab.client.create_plan(
            plan_payload(env.flow["id"], "MEMORY_D1"), fab_planner_headers()
        )

        body = validate_error(response, ERR_PRODUCT_FAMILY_MISMATCH, 422)
        assert body["error_id"] == ERR_PRODUCT_FAMILY_MISMATCH
        assert fab.count(
            fab.client.list_plans(fab_planner_headers(), {"flow_id": env.flow["id"]})
        ) == 0

    def test_a_commit_whose_surcharge_overruns_the_budget_persists_nothing(self, fab):
        """350 base hours already exceed the 100.0 budget, and TIER_3 makes it worse.

        PRD: "Seventh, if `committed_hours` is strictly greater than
        `capacity_budget_hours`, the commit is rejected with
        `ERR_CAPACITY_BUDGET_EXCEEDED` and nothing is persisted — the plan stays
        `DRAFT` with `committed_hours` at 0.0, `surcharge_hours` at 0.0 and
        `commitment_tier` at `TIER_0`."

        Design: Corner/validations/commit_whose_surcharged_hours_overrun_the_budget_returns_capacity_budget_exceeded
        """
        env = build_line(
            fab,
            single_step_spec(
                steps=[StepSpec(10, "LITHO-1", 7.0)],
                planned_wafer_starts=50,
                capacity_budget_hours=100.0,
                commit_plan=False,
                lots=[],
            ),
        )
        assert_hours(env.flow["total_standard_hours"], 7.0, "total_standard_hours")
        assert env.plan["status"] == "DRAFT"
        assert_hours(env.plan["committed_hours"], 0.0, "committed_hours")

        response = fab.client.commit_plan(env.plan["id"], fab_planner_headers())

        body = validate_error(response, ERR_CAPACITY_BUDGET_EXCEEDED, 409)
        assert body["error_id"] == ERR_CAPACITY_BUDGET_EXCEEDED
        stored = fab.read_plan(env.plan["id"])
        assert_fields(stored, status="DRAFT", commitment_tier="TIER_0")
        assert_hours(stored["committed_hours"], 0.0, "committed_hours")
        assert_hours(stored["surcharge_hours"], 0.0, "surcharge_hours")

    def test_a_release_that_would_overdraw_the_wafer_starts_is_refused(self, fab):
        """Eight of ten starts are drawn, so a three-wafer lot cannot follow.

        PRD: "The wafer-start ledger is then evaluated: the candidate total is the
        plan's `released_wafer_starts` plus the lot's `wafer_count`, and if that
        candidate is strictly greater than `planned_wafer_starts` the release is
        rejected with `ERR_PLAN_STARTS_EXCEEDED`."

        Design: Corner/validations/releasing_one_lot_too_many_returns_plan_starts_exceeded
        """
        env = build_line(
            fab,
            single_step_spec(
                planned_wafer_starts=10,
                lots=[LotSpec("LOT-001", 8), LotSpec("LOT-002", 3, release=False)],
            ),
        )
        priced = fab.read_plan(env.plan["id"])
        assert_hours(priced["committed_hours"], 20.00, "committed_hours")
        assert priced["commitment_tier"] == "TIER_0"
        assert priced["released_wafer_starts"] == 8

        response = fab.client.release_lot(
            env.lots[1]["id"],
            release_lot_payload(priced["version"]),
            fab_planner_headers(),
        )

        body = validate_error(response, ERR_PLAN_STARTS_EXCEEDED, 409)
        assert body["error_id"] == ERR_PLAN_STARTS_EXCEEDED
        after = fab.read_plan(env.plan["id"])
        assert after["released_wafer_starts"] == 8
        assert after["status"] == "COMMITTED"
        held_back = fab.read_lot(env.lots[1]["id"])
        assert_lot_state(held_back, flow_state="PLANNED")
        assert_nulls(held_back, "released_at")


# --------------------------------------------------------------------------
# Wafer conservation across splits and rejoins
# --------------------------------------------------------------------------


class TestSplitAndRejoin:
    def test_a_split_may_not_carry_away_the_parents_last_wafer(self, fab):
        """Splitting all 25 wafers would empty the parent, which the range forbids.

        PRD: "The parent's `flow_state` must be `RELEASED` or `IN_PROCESS`, and
        `split_wafer_count` must be at least 1 and strictly less than the parent's
        current `wafer_count` — a split that would empty or over-draw the parent is
        rejected with `ERR_INVALID_SPLIT_QUANTITY`."

        Design: Corner/validations/splitting_off_every_wafer_returns_invalid_split_quantity
        """
        env = build_line(
            fab,
            single_step_spec(
                planned_wafer_starts=30, lots=[LotSpec("LOT-001", 25)]
            ),
        )
        parent = fab.read_lot(env.lots[0]["id"])
        assert parent["wafer_count"] == 25
        assert parent["origin_wafer_count"] == 25

        response = fab.client.split_lot(
            parent["id"],
            split_payload(parent["version"], 25, "LOT-001-S1"),
            process_engineer_headers(),
        )

        body = validate_error(response, ERR_INVALID_SPLIT_QUANTITY, 422)
        assert body["error_id"] == ERR_INVALID_SPLIT_QUANTITY
        unchanged = fab.read_lot(parent["id"])
        assert unchanged["wafer_count"] == 25
        assert unchanged["version"] == parent["version"]
        assert fab.count(
            fab.client.list_lots(fab_planner_headers(), {"parent_lot_id": parent["id"]})
        ) == 0

    def test_a_production_lot_has_no_parent_to_rejoin(self, fab):
        """Rejoin only exists for engineering splits born held under a parent.

        PRD: "It requires the lot's `hold_state` to be `ENGINEERING_HOLD` and the
        lot to be an `ENGINEERING_SPLIT` with a non-null `parent_lot_id`, otherwise
        `ERR_NOT_A_SPLIT_LOT`."

        Design: Corner/validations/rejoin_on_a_production_lot_returns_not_a_split_lot
        """
        env = build_line(
            fab,
            single_step_spec(
                planned_wafer_starts=30, lots=[LotSpec("LOT-001", 25)]
            ),
        )
        assert env.lots[0]["lot_type"] == "PRODUCTION"
        assert_nulls(env.lots[0], "parent_lot_id")

        response = fab.client.rejoin_lot(
            env.lots[0]["id"], process_engineer_headers()
        )

        body = validate_error(response, ERR_NOT_A_SPLIT_LOT, 422)
        assert body["error_id"] == ERR_NOT_A_SPLIT_LOT
        stored = fab.read_lot(env.lots[0]["id"])
        assert stored["wafer_count"] == 25
        assert_lot_state(stored, flow_state="RELEASED", hold_state="NONE")


# --------------------------------------------------------------------------
# The rework rewind and its two guards
# --------------------------------------------------------------------------


class TestReworkGuards:
    def test_a_step_with_no_rework_target_cannot_be_rewound(self, fab):
        """The material is held for rework, but this step declares nowhere to go.

        PRD: "Rework is the `ProcessEngineer`'s rewind of a held lot. It requires
        the lot's `hold_state` to be `SPC_HOLD`, requires the excursion named by
        `hold_excursion_id` to carry a `disposition` of `REWORK`, requires the
        lot's `rework_count` to be strictly below the limit of 2 rewinds — a third
        attempt is rejected with `ERR_REWORK_LIMIT_EXCEEDED` — and requires the
        step at the lot's `current_step_seq` to declare a non-null
        `rework_target_step_id`, otherwise `ERR_REWORK_TARGET_NOT_SET`."

        Design: Corner/validations/rework_at_a_step_with_no_rework_target_returns_rework_target_not_set
        """
        env = build_line(
            fab,
            single_step_spec(
                steps=[
                    StepSpec(10, "LITHO-1", 2.0, metrology_required=True),
                    StepSpec(20, "LITHO-2", 2.0),
                ],
                charts=[ChartSpec(step_ix=0, param_name="CD-10")],
            ),
        )
        assert_nulls(env.steps[0], "rework_target_step_id")
        assert_hours(env.plan["committed_hours"], 40.00, "committed_hours")

        raised = raise_spc_excursion(fab, env, 112.0, step_ix=0, lot_ix=0)
        assert raised.measurement["classification"] == "OUT_OF_SPEC"
        assert_ratio(raised.measurement["deviation_sigma"], 6.0000, "deviation_sigma")
        contained = fab.contain(raised.excursion["id"], "SPC_CHART")
        assert contained["status"] == "CONTAINED"
        assert (
            fab.track_out(raised.run["id"], env.operators[0]["id"])["status"]
            == "COMPLETED"
        )
        dispositioned = fab.disposition(raised.excursion["id"], "REWORK")
        assert_fields(dispositioned, disposition="REWORK", status="DISPOSITIONED")

        response = fab.client.rework_lot(
            env.lots[0]["id"], process_engineer_headers()
        )

        body = validate_error(response, ERR_REWORK_TARGET_NOT_SET, 422)
        assert body["error_id"] == ERR_REWORK_TARGET_NOT_SET
        stored = fab.read_lot(env.lots[0]["id"])
        assert_lot_state(
            stored,
            flow_state="IN_PROCESS",
            hold_state="SPC_HOLD",
            current_step_seq=10,
        )
        assert stored["rework_count"] == 0
        assert fab.read_chart(env.charts[0]["id"])["status"] == "MONITORING"

    def test_a_third_rewind_of_the_same_lot_exhausts_the_rework_budget(self, fab):
        """Two rewinds are spent; the third excursion leaves the lot held for good.

        PRD: "Rework is the `ProcessEngineer`'s rewind of a held lot. It requires
        the lot's `hold_state` to be `SPC_HOLD`, requires the excursion named by
        `hold_excursion_id` to carry a `disposition` of `REWORK`, requires the
        lot's `rework_count` to be strictly below the limit of 2 rewinds — a third
        attempt is rejected with `ERR_REWORK_LIMIT_EXCEEDED` — and requires the
        step at the lot's `current_step_seq` to declare a non-null
        `rework_target_step_id`, otherwise `ERR_REWORK_TARGET_NOT_SET`."

        PRD: "Regardless of which `disposition` was chosen, any chart suspended by
        this excursion's containment is driven `SUSPENDED → MONITORING`, with
        `consecutive_same_side_count` reset to 0 and `last_side` reset to `NONE`, so
        the run rule restarts from a clean slate; that is what closes the chart
        cycle `MONITORING → SUSPENDED → MONITORING`."

        Design: Corner/validations/a_third_rework_of_the_same_lot_returns_rework_limit_exceeded
        """
        env = build_line(
            fab,
            single_step_spec(
                steps=[
                    StepSpec(10, "LITHO-1", 2.0),
                    StepSpec(
                        20,
                        "LITHO-2",
                        3.0,
                        metrology_required=True,
                        rework_target_ix=0,
                    ),
                    StepSpec(30, "LITHO-3", 2.0),
                ],
                charts=[ChartSpec(step_ix=1, param_name="CD-20")],
                planned_wafer_starts=10,
                capacity_budget_hours=200.0,
            ),
        )
        assert_hours(env.flow["total_standard_hours"], 7.0, "total_standard_hours")
        assert_hours(env.plan["committed_hours"], 70.00, "committed_hours")
        assert env.steps[1]["rework_target_step_id"] == env.steps[0]["id"]
        lot_id = env.lots[0]["id"]
        operator_id = env.operators[0]["id"]

        for expected_count in (1, 2):
            complete_step(fab, env, step_ix=0, lot_ix=0)
            loop = raise_spc_excursion(fab, env, 112.0, step_ix=1, lot_ix=0)
            fab.contain(loop.excursion["id"], "SPC_CHART")
            fab.track_out(loop.run["id"], operator_id)
            fab.disposition(loop.excursion["id"], "REWORK")
            rewound = fab.rework_lot(lot_id)
            assert rewound["rework_count"] == expected_count
            # The rework target is step 10, so the lot waits at sequence 9.
            assert_lot_state(rewound, current_step_seq=9, hold_state="NONE")

        complete_step(fab, env, step_ix=0, lot_ix=0)
        third = raise_spc_excursion(fab, env, 112.0, step_ix=1, lot_ix=0)
        assert third.measurement["classification"] == "OUT_OF_SPEC"
        assert third.measurement["run_rule_triggered"] is False
        fab.contain(third.excursion["id"], "SPC_CHART")
        closed = fab.track_out(third.run["id"], operator_id)
        assert closed["status"] == "COMPLETED"
        assert_hours(closed["actual_hours"], 0.00, "actual_hours")
        assert fab.disposition(third.excursion["id"], "REWORK")["disposition"] == "REWORK"

        response = fab.client.rework_lot(lot_id, process_engineer_headers())

        body = validate_error(response, ERR_REWORK_LIMIT_EXCEEDED, 409)
        assert body["error_id"] == ERR_REWORK_LIMIT_EXCEEDED
        stranded = fab.read_lot(lot_id)
        assert stranded["rework_count"] == 2
        assert_lot_state(
            stranded,
            flow_state="IN_PROCESS",
            hold_state="SPC_HOLD",
            current_step_seq=20,
        )
        assert stranded["wafer_count"] == 3
        assert stranded["origin_wafer_count"] == 3
        tool = fab.read_equipment(env.equipments[0]["id"])
        assert_hours(
            tool["available_capacity_hours"], 720.00, "available_capacity_hours"
        )
        assert_hours(tool["hours_since_pm"], 0.0, "hours_since_pm")
        assert tool["state"] == "IDLE"
        assert fab.read_chamber(env.chambers[0]["id"])["occupancy_state"] == "FREE"
        assert_fields(
            fab.read_chart(env.charts[0]["id"]),
            violation_count=3,
            status="MONITORING",
            consecutive_same_side_count=0,
        )


# --------------------------------------------------------------------------
# Sort admissibility, wafer-map consistency and binning
# --------------------------------------------------------------------------


class TestSortAdmissibility:
    def test_sort_results_cannot_be_filed_on_a_lot_that_never_ran(self, fab):
        """The lot is merely RELEASED, so it is nowhere near the sort floor.

        PRD: "The request names the `lot_id`, which must have `flow_state`
        `AT_SORT` or the request is rejected with `ERR_LOT_INVALID_STATE`, and
        which must not be on hold or the request is rejected with
        `ERR_LOT_ON_HOLD`."

        Design: Corner/validations/die_sort_run_on_a_released_lot_returns_lot_invalid_state
        """
        env = build_line(fab, single_step_spec())
        assert_lot_state(env.lots[0], flow_state="RELEASED")

        response = fab.client.create_die_sort_run(
            die_sort_payload(
                env.lots[0]["id"],
                [wafer_result(1, 100, 90, edge_ring_fails=10)],
                gross_die_per_wafer=100,
                baseline_yield=0.92,
            ),
            yield_engineer_headers(),
        )

        body = validate_error(response, ERR_LOT_INVALID_STATE, 409)
        assert body["error_id"] == ERR_LOT_INVALID_STATE
        assert fab.count(
            fab.client.list_die_sort_runs(
                yield_engineer_headers(), {"lot_id": env.lots[0]["id"]}
            )
        ) == 0
        assert_lot_state(fab.read_lot(env.lots[0]["id"]), flow_state="RELEASED")

    def test_failure_counts_that_do_not_close_the_wafer_are_refused(self, fab):
        """Ten die failed but only five were attributed, so the element is rejected.

        PRD: "Per element, `good_die` must not exceed `tested_die`, and the four
        failure counts must sum to exactly `tested_die` minus `good_die`; an empty
        array or any element failing either rule is rejected with
        `ERR_WAFER_RESULT_INCONSISTENT`."

        Design: Corner/validations/wafer_results_whose_fail_counts_do_not_close_returns_wafer_result_inconsistent
        """
        env = build_line(fab, single_step_spec())
        advance_to_at_sort(fab, env, lot_ix=0)
        assert_lot_state(fab.read_lot(env.lots[0]["id"]), flow_state="AT_SORT")

        response = fab.client.create_die_sort_run(
            die_sort_payload(
                env.lots[0]["id"],
                [wafer_result(1, 100, 90, edge_ring_fails=5)],
                gross_die_per_wafer=100,
                baseline_yield=0.92,
            ),
            yield_engineer_headers(),
        )

        body = validate_error(response, ERR_WAFER_RESULT_INCONSISTENT, 422)
        assert body["error_id"] == ERR_WAFER_RESULT_INCONSISTENT
        assert fab.count(
            fab.client.list_die_sort_runs(
                yield_engineer_headers(), {"lot_id": env.lots[0]["id"]}
            )
        ) == 0
        assert fab.count(fab.client.list_excursions(yield_engineer_headers())) == 0
        assert_lot_state(fab.read_lot(env.lots[0]["id"]), flow_state="AT_SORT")

    def test_a_flawless_wafer_set_sorts_at_full_yield_with_no_signature(self, fab):
        """Every die passes, so loss floors at zero and no mode can dominate.

        PRD: "When there are no fails at all, `dominant_signature` is `NONE` and
        no division is attempted."

        PRD: "A sort run opens in `SORTED` `status`, with `premium_target_die`,
        `standard_target_die`, `premium_die`, `standard_die` and `value_die` all at
        0 before binning."

        Design: Corner/validations/a_zero_fail_wafer_set_sorts_at_full_yield_with_no_signature
        """
        env = build_line(fab, single_step_spec())

        sort_run = sorted_run(
            fab,
            env,
            [
                wafer_result(1, 100, 100),
                wafer_result(2, 100, 100),
                wafer_result(3, 100, 100),
            ],
            gross_die_per_wafer=100,
            baseline_yield=0.92,
        )

        assert_ratio(sort_run["sort_yield"], 1.0000, "sort_yield")
        # The lot beat its baseline, so the loss ratio floors at zero.
        assert_ratio(sort_run["yield_loss_ratio"], 0.0000, "yield_loss_ratio")
        assert sort_run["good_die_total"] == 300
        assert_fields(
            sort_run,
            dominant_signature="NONE",
            status="SORTED",
            premium_die=0,
            standard_die=0,
            value_die=0,
        )
        assert fab.count(
            fab.client.list_excursions(
                yield_engineer_headers(), {"source_type": "DIE_SORT"}
            )
        ) == 0
        assert_lot_state(fab.read_lot(env.lots[0]["id"]), flow_state="AT_SORT")

    def test_a_binned_sort_run_refuses_a_second_allocation(self, fab):
        """The waterfall ran once; the buckets are frozen and the lot is closed.

        PRD: "Binning requires the run's `status` to be `SORTED` — a second
        attempt is rejected with `ERR_SORT_RUN_ALREADY_BINNED` — and requires the
        lot to still be `AT_SORT`."

        Design: Corner/validations/binning_an_already_binned_sort_run_returns_sort_run_already_binned
        """
        env = build_line(fab, single_step_spec())
        sort_run = sorted_run(
            fab,
            env,
            [
                wafer_result(1, 100, 90, edge_ring_fails=10),
                wafer_result(2, 100, 90, edge_ring_fails=10),
                wafer_result(3, 100, 90, edge_ring_fails=10),
            ],
            gross_die_per_wafer=100,
            baseline_yield=0.92,
        )
        assert_ratio(sort_run["sort_yield"], 0.9000, "sort_yield")
        assert sort_run["good_die_total"] == 270
        binned = fab.bin_sort_run(sort_run["id"], 50, 60)
        assert_fields(
            binned, premium_die=50, standard_die=60, value_die=160, status="BINNED"
        )

        response = fab.client.bin_die_sort_run(
            sort_run["id"], bin_payload(200, 70), yield_engineer_headers()
        )

        body = validate_error(response, ERR_SORT_RUN_ALREADY_BINNED, 409)
        assert body["error_id"] == ERR_SORT_RUN_ALREADY_BINNED
        assert_fields(
            fab.read_die_sort_run(sort_run["id"]),
            premium_die=50,
            standard_die=60,
            value_die=160,
            status="BINNED",
        )
        assert_lot_state(fab.read_lot(env.lots[0]["id"]), flow_state="COMPLETED")
