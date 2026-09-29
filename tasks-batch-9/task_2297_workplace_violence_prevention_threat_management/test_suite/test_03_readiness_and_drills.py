"""Inspection readiness: the rounded subtotal, the penalty band and the drill credit boundary."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    ApiClient,
    assert_penalty_band_from_rounded_subtotal,
    assert_plan_metrics,
    assert_plan_state,
    assert_readiness,
    assert_two_decimal_value,
    build_drill_execution,
    make_safety_officer_headers,
    read_plan,
    setup_draft_plan,
    setup_drilled_plan,
    setup_employee,
    setup_monitoring_case,
    setup_work_area,
    setup_worksite_with_area,
)


def _plan_scoring_seventy_four_point_nine_nine_nine(api: ApiClient):
    """A REVIEW_DUE plan with one live assessment of three areas, two credited drills and one log entry."""
    ctx = setup_monitoring_case(api)
    ctx = setup_drilled_plan(api, ctx)
    for drill_key, findings in (("drill_one", 3), ("drill_two", 1)):
        get_success_data(
            api.execute_drill(
                ctx[drill_key]["id"],
                build_drill_execution(12, findings_count=findings),
                ctx["headers"]["safety_officer"],
            )
        )
    ctx["lone_area"] = setup_work_area(
        api,
        ctx["worksite"]["id"],
        name="Night Yard",
        job_function="FIELD_SERVICE",
        public_access_flag=False,
        lone_worker_flag=True,
        night_shift_flag=False,
        occupancy_cap=4,
    )
    ctx["vault_area"] = setup_work_area(
        api,
        ctx["worksite"]["id"],
        name="Cash Vault",
        job_function="CASH_HANDLING",
        public_access_flag=True,
        lone_worker_flag=False,
        night_shift_flag=True,
        occupancy_cap=4,
    )
    return ctx


class TestReadinessSubtotalAndPenaltyBand:
    """The five weighted components sum to 74.999 and round into the subtotal before banding."""

    def test_five_weighted_components_round_into_a_subtotal_of_seventy_five(
        self, api: ApiClient
    ) -> None:
        """One third coverage, full training, a 75.00 percent register and two credited drills sum to 74.999.

        PRD: "Step 1 adds the five components and rounds the sum half-up to two decimal places into `readiness_subtotal`."
        Design: Difficulty/combinatorial_formula/readiness_penalty_band_keyed_on_rounded_subtotal
        """
        ctx = _plan_scoring_seventy_four_point_nine_nine_nine(api)

        plan = read_plan(api, ctx)

        assert_plan_metrics(
            plan,
            hazard_coverage_pct=33.33,
            training_compliance_pct=100.00,
            log_completeness_pct=75.00,
            drills_completed_12mo=2,
            unmitigated_hazard_count=1,
            overdue_action_count=0,
        )
        assert_readiness(plan, subtotal=75.00)

    def test_penalty_band_keyed_on_the_rounded_subtotal_costs_four_point_five_zero(
        self, api: ApiClient
    ) -> None:
        """Banding the rounded 75.00 as ADEQUATE costs 4.50 points, not the 9.00 a WEAK band would cost.

        PRD: "The rounding is decisive here rather than cosmetic — a raw sum of 74.999 rounds to a subtotal of exactly 75.00 and therefore bands as `ADEQUATE` at 0.06, whereas banding on the raw figure would have given `WEAK` at 0.12 and a materially different final score."
        Design: Difficulty/combinatorial_formula/readiness_penalty_band_keyed_on_rounded_subtotal
        """
        ctx = _plan_scoring_seventy_four_point_nine_nine_nine(api)

        plan = read_plan(api, ctx)

        assert_readiness(
            plan,
            subtotal=75.00,
            penalty_band="ADEQUATE",
            penalty_points=4.50,
            score=70.50,
            inspection_ready=False,
        )
        assert plan["readiness_penalty_band"] != "WEAK"
        assert_penalty_band_from_rounded_subtotal(plan)
        assert_plan_state(plan, status="REVIEW_DUE", compliance_posture="RESTRICTED")


class TestDrillParticipationCredit:
    """Twelve of twenty participants is exactly the inclusive credit boundary."""

    def _two_scheduled_drills(self, api: ApiClient):
        ctx = setup_worksite_with_area(api)
        ctx["so"] = setup_employee(
            api,
            ctx["worksite"]["id"],
            ctx["work_area"]["id"],
            full_name="Sofia Ortiz",
            job_function="SECURITY",
        )
        ctx["headers"] = {"safety_officer": make_safety_officer_headers(ctx["so"]["id"])}
        ctx = setup_draft_plan(api, ctx)
        return setup_drilled_plan(api, ctx)

    def test_participation_of_exactly_sixty_percent_credits_the_drill(
        self, api: ApiClient
    ) -> None:
        """Twelve participants of a declared headcount of twenty is 60.00 percent and credits the plan.

        PRD: "`credited` becomes true when the drill is `EXECUTED` and `participation_pct` is at least 60.00 — an inclusive boundary."
        Design: Difficulty/boundary_precision_check/drill_participation_exactly_sixty_percent_credits_the_drill
        """
        ctx = self._two_scheduled_drills(api)

        executed = get_success_data(
            api.execute_drill(
                ctx["drill_one"]["id"],
                build_drill_execution(12, findings_count=3),
                ctx["headers"]["safety_officer"],
            )
        )

        assert_two_decimal_value(executed["participation_pct"], 60.00, "participation_pct")
        assert executed["credited"] is True
        assert executed["status"] == "EXECUTED"
        assert executed["executed_at"] == "2026-08-01T00:00:00Z"
        assert executed["findings_count"] == 3
        assert_plan_metrics(read_plan(api, ctx), drills_completed_12mo=1)

    def test_participation_of_fifty_five_percent_leaves_the_drill_uncredited(
        self, api: ApiClient
    ) -> None:
        """Eleven of twenty is 55.00 percent: the drill still executes but the credited count holds at one.

        PRD: "A successful execution moves the drill `SCHEDULED` → `EXECUTED`, writes `executed_at` from the logical clock, and computes `participation_pct` as `participant_count` divided by the worksite's `employee_count`, multiplied by 100, rounded half-up to two decimals."
        Design: Difficulty/boundary_precision_check/drill_participation_exactly_sixty_percent_credits_the_drill
        """
        ctx = self._two_scheduled_drills(api)
        get_success_data(
            api.execute_drill(
                ctx["drill_one"]["id"],
                build_drill_execution(12, findings_count=3),
                ctx["headers"]["safety_officer"],
            )
        )

        executed = get_success_data(
            api.execute_drill(
                ctx["drill_two"]["id"],
                build_drill_execution(11, findings_count=0),
                ctx["headers"]["safety_officer"],
            )
        )

        assert_two_decimal_value(executed["participation_pct"], 55.00, "participation_pct")
        assert executed["credited"] is False
        assert executed["status"] == "EXECUTED"
        assert_plan_metrics(read_plan(api, ctx), drills_completed_12mo=1)
