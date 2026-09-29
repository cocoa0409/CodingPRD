"""Case actions depend on rows they do not own: the governing plan's posture and the escort's training."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assert_escort_ledger,
    assert_plan_state,
    assert_total_count,
    build_escort_action,
    build_plan_submission,
    build_post_incident_action,
    move_clock,
    read_employee,
    read_plan,
    setup_monitoring_case,
    setup_monitoring_case_with_escort,
    run_daily_sweep,
)


class TestFrozenGoverningPlan:
    """Resubmitting the plan for periodic review freezes every case action behind it."""

    def _case_on_a_resubmitted_plan(self, api: ApiClient):
        ctx = setup_monitoring_case(api)
        ctx["plan"] = read_plan(api, ctx)
        api.submit_prevention_plan(
            ctx["plan"]["id"],
            build_plan_submission(
                submission_note="Periodic review after the substantiated incident."
            ),
            ctx["headers"]["safety_officer"],
        )
        return ctx

    def test_resubmitting_a_review_due_plan_freezes_it_and_clears_the_activation(
        self, api: ApiClient
    ) -> None:
        """The periodic-review submission takes the posture from RESTRICTED to FROZEN and wipes the activation.

        PRD: "From `REVIEW_DUE`, the safety officer submits again — closing the periodic-review cycle — which stamps a new `submitted_by_employee_id`, **clears** `activated_by_employee_id` and `review_due_date`, and moves the posture from `RESTRICTED` all the way to `FROZEN`, at which point case actions against cases governed by that plan are refused with `ERR_PLAN_POSTURE_FROZEN`."
        Design: Difficulty/cross_entity_state_dependency/case_action_rejected_while_governing_prevention_plan_is_frozen
        """
        ctx = setup_monitoring_case(api)
        assert_plan_state(
            read_plan(api, ctx), status="REVIEW_DUE", compliance_posture="RESTRICTED"
        )

        ctx = self._case_on_a_resubmitted_plan(api)

        plan = read_plan(api, ctx)
        assert_plan_state(
            plan, status="IN_REVIEW", compliance_posture="FROZEN", inspection_ready=False
        )
        assert plan["submitted_by_employee_id"] == ctx["so"]["id"]
        assert plan["activated_by_employee_id"] is None
        assert plan["review_due_date"] is None

    def test_no_case_action_may_be_recorded_while_the_plan_is_frozen(
        self, api: ApiClient
    ) -> None:
        """A counselling referral on the monitoring case is refused, and no row reaches the register.

        PRD: "A `FROZEN` posture is a hard stop on operational writes: no case action may be recorded against a case whose plan is frozen, and no team may convene on such a case, both refused with `ERR_PLAN_POSTURE_FROZEN`."
        Design: Difficulty/cross_entity_state_dependency/case_action_rejected_while_governing_prevention_plan_is_frozen
        """
        ctx = self._case_on_a_resubmitted_plan(api)

        response = api.create_case_action(
            build_post_incident_action(
                ctx["case"]["id"],
                "COUNSELING_REFERRAL",
                ctx["hr"]["id"],
                "2026-08-08T00:00:00Z",
            ),
            ctx["headers"]["hr_partner"],
        )

        validate_error(response, ApiErrorId.PLAN_POSTURE_FROZEN, 409)
        assert_total_count(
            api.list_case_actions(
                ctx["headers"]["security_coordinator"], {"case_id": ctx["case"]["id"]}
            ),
            0,
        )


class TestLapsedEscortQualification:
    """An escort whose escort-required refresh has lapsed can no longer be named."""

    def _case_with_a_lapsed_escort(self, api: ApiClient):
        ctx = setup_monitoring_case_with_escort(api, refresh_interval_days=30)
        move_clock(api, "2026-08-31T00:00:00Z")
        ctx["sweep"] = run_daily_sweep(api)
        return ctx

    def test_the_nightly_sweep_lapses_the_completed_assignment_at_its_expiry(
        self, api: ApiClient
    ) -> None:
        """A thirty-day refresh completed on 1 August expires on the 31st and lapses in that day's sweep.

        PRD: "Training assignments lapse: an `ASSIGNED` assignment whose `due_at` is strictly before the clock becomes `EXPIRED`, and a `COMPLETED` assignment whose `expires_at` is at or before the clock becomes `EXPIRED`. Every affected employee's `training_current` is then refreshed."
        Design: Difficulty/cross_entity_state_dependency/security_escort_rejected_when_required_training_assignment_expired
        """
        ctx = setup_monitoring_case_with_escort(api, refresh_interval_days=30)
        assert ctx["escort_assignment"]["expires_at"] == "2026-08-31T00:00:00Z"

        move_clock(api, "2026-08-31T00:00:00Z")
        sweep = run_daily_sweep(api)

        assert sweep["training_expired_count"] == 1
        refreshed = get_success_data(
            api.get_training_assignment(
                ctx["escort_assignment"]["id"], ctx["headers"]["hr_partner"]
            )
        )
        assert refreshed["status"] == "EXPIRED"
        escort = read_employee(api, ctx["escort"]["id"])
        assert escort["training_current"] is False
        assert escort["employment_status"] == "ACTIVE"

    def test_an_escort_booking_on_the_lapsed_escort_is_refused_as_unqualified(
        self, api: ApiClient
    ) -> None:
        """The employee row never changed, yet naming her as escort inside the window is refused.

        PRD: "The lapse has teeth beyond the metrics: an employee whose escort-required module has lapsed to `EXPIRED` can no longer be named as escort on a new protective measure, which is refused with `ERR_ESCORT_NOT_QUALIFIED`, even though nothing about the employee row itself changed."
        Design: Difficulty/cross_entity_state_dependency/security_escort_rejected_when_required_training_assignment_expired
        """
        ctx = self._case_with_a_lapsed_escort(api)

        response = api.create_case_action(
            build_escort_action(
                ctx["case"]["id"],
                ctx["rep"]["id"],
                ctx["escort"]["id"],
                "2026-08-06T00:00:00Z",
                "2026-08-06T04:00:00Z",
            ),
            ctx["headers"]["security_coordinator"],
        )

        validate_error(response, ApiErrorId.ESCORT_NOT_QUALIFIED, 409)
        assert_escort_ledger(read_employee(api, ctx["escort"]["id"]), 0)
        assert_total_count(
            api.list_case_actions(
                ctx["headers"]["security_coordinator"], {"case_id": ctx["case"]["id"]}
            ),
            0,
        )
