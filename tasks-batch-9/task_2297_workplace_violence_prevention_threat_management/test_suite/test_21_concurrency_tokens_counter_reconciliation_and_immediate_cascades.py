"""Consumed version tokens, counters that reconcile across the ops run, and one decide seen at once."""

from typing import Any, Dict

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    ApiClient,
    ApiErrorId,
    add_hazard_assessment,
    add_post_incident_action,
    assert_case_state,
    assert_hazard_assessment,
    assert_plan_metrics,
    assert_plan_state,
    assert_protection,
    assert_readiness,
    assert_report_dimensions,
    assert_risk_scores,
    assert_sweep_counters,
    assert_total_count,
    assign_training,
    build_action_completion,
    build_decision,
    build_hazard_assessment,
    build_training_assignment,
    complete_training,
    make_hr_partner_headers,
    make_safety_officer_headers,
    make_site_manager_headers,
    move_clock,
    read_case,
    read_case_action,
    read_employee,
    read_plan,
    read_report,
    read_work_area,
    read_worksite,
    run_daily_sweep,
    setup_active_plan,
    setup_deliberating_case,
    setup_draft_plan,
    setup_employee,
    setup_monitoring_case,
    setup_screened_plan,
    setup_submitted_plan,
    setup_training_cohort,
    setup_worksite_with_area,
)

#: A worse screening of the same area: six incidents and a single-staffed shift, scoring 80.00.
WORSE_SCREENING = {
    "reported_incident_count": 6,
    "min_staff_per_shift": 1,
}


def _single_learner_worksite(api: ApiClient) -> Dict[str, Any]:
    """An ACTIVE plan whose entire training population is one ADMIN worker who is current."""
    ctx: Dict[str, Any] = setup_worksite_with_area(api)
    worksite_id = ctx["worksite"]["id"]
    area_id = ctx["work_area"]["id"]
    ctx["so"] = setup_employee(
        api, worksite_id, area_id, full_name="Sofia Ortiz", job_function="SECURITY"
    )
    ctx["sm"] = setup_employee(
        api, worksite_id, area_id, full_name="Marcus Reed", job_function="SECURITY"
    )
    ctx["hr"] = setup_employee(
        api, worksite_id, area_id, full_name="Priya Nair", job_function="SECURITY"
    )
    ctx["headers"] = {
        "safety_officer": make_safety_officer_headers(ctx["so"]["id"]),
        "site_manager": make_site_manager_headers(ctx["sm"]["id"]),
        "hr_partner": make_hr_partner_headers(ctx["hr"]["id"]),
    }
    ctx["learner"] = setup_employee(
        api, worksite_id, area_id, full_name="Wendy Cole", job_function="ADMIN"
    )
    ctx = setup_training_cohort(api, ctx)
    assignment = assign_training(
        api, ctx, ctx["learner"]["id"], due_at="2026-08-20T00:00:00Z"
    )
    ctx["assignment"] = complete_training(
        api, ctx, assignment["id"], ctx["learner"]["id"], score=88
    )
    ctx = setup_draft_plan(api, ctx)
    ctx = setup_screened_plan(api, ctx)
    ctx = setup_submitted_plan(api, ctx)
    return setup_active_plan(api, ctx)


class TestPlanVersionTokenIsConsumedByTheAssessmentItGuards:
    """The plan version is the token for a child table, so one screening spends it."""

    def test_replaying_the_observed_token_is_refused_and_a_fresh_read_supersedes(
        self, api: ApiClient
    ) -> None:
        """The stale supersede changes nothing; the retry on the re-read token demotes the first row.

        PRD: "If `expected_plan_version` does not equal the plan's current `version`, the create is refused with `ERR_STALE_PLAN_VERSION` (412): the client's view of the plan is stale, so the supersede it is asking for would discard an assessment it has never seen."
        Design: Corner/cross_cutting_complexity_layers/expected_plan_version_guard_refuses_the_stale_write_and_admits_the_retry
        """
        ctx = setup_draft_plan(api)
        officer = ctx["headers"]["safety_officer"]
        observed_version = ctx["plan"]["version"]
        first = add_hazard_assessment(api, ctx)
        current = read_plan(api, ctx)
        assert current["version"] == observed_version + 1

        stale = api.create_hazard_assessment(
            build_hazard_assessment(
                ctx["plan"]["id"],
                ctx["work_area"]["id"],
                observed_version,
                **WORSE_SCREENING,
            ),
            officer,
        )

        validate_error(stale, ApiErrorId.STALE_PLAN_VERSION, 412)
        assert read_plan(api, ctx)["version"] == current["version"]
        assert (
            get_success_data(api.get_hazard_assessment(first["id"], officer))["status"]
            == "SCREENING"
        )

        retried = get_success_data(
            api.create_hazard_assessment(
                build_hazard_assessment(
                    ctx["plan"]["id"],
                    ctx["work_area"]["id"],
                    current["version"],
                    **WORSE_SCREENING,
                ),
                officer,
            ),
            201,
        )

        assert_hazard_assessment(
            retried,
            hazard_score=80.00,
            control_tier="TIER_1_ENGINEERING",
            score_variant="SCREENING",
            status="SCREENING",
            mitigation_verified=False,
        )
        assert (
            get_success_data(api.get_hazard_assessment(first["id"], officer))["status"]
            == "SUPERSEDED"
        )
        assert read_plan(api, ctx)["version"] == current["version"] + 1
        assert read_work_area(api, ctx["work_area"]["id"])["current_hazard_score"] is None
        assert_plan_metrics(read_plan(api, ctx), hazard_coverage_pct=100.00)


class TestEmployeeVersionTokenIsConsumedByTheRefreshItGuards:
    """The annual refresh cannot ride the token that created the assignment it supersedes."""

    def test_the_second_refresh_needs_a_fresh_read_before_it_may_supersede(
        self, api: ApiClient
    ) -> None:
        """The learner keeps exactly one live assignment until the caller re-reads her version.

        PRD: "If it does not equal the employee's current `version`, the create is refused with `ERR_STALE_EMPLOYEE_VERSION` (412), because the learner record has advanced — through an earlier refresh, a completion, or a separation — since the client last read it."
        Design: Corner/cross_cutting_complexity_layers/expected_employee_version_guard_refuses_a_second_refresh_built_on_a_consumed_token
        """
        ctx = setup_training_cohort(api)
        hr_headers = ctx["headers"]["hr_partner"]
        learner = setup_employee(
            api,
            ctx["worksite"]["id"],
            ctx["work_area"]["id"],
            full_name="Wendy Cole",
            job_function="ADMIN",
        )
        observed_version = learner["version"]
        first = assign_training(
            api, ctx, learner["id"], due_at="2026-08-20T00:00:00Z"
        )
        current = read_employee(api, learner["id"])
        assert current["version"] == observed_version + 1

        stale = api.create_training_assignment(
            build_training_assignment(
                learner["id"],
                ctx["module"]["id"],
                observed_version,
                due_at="2026-09-20T00:00:00Z",
            ),
            hr_headers,
        )

        validate_error(stale, ApiErrorId.STALE_EMPLOYEE_VERSION, 412)
        held = assert_total_count(
            api.list_training_assignments(hr_headers, {"employee_id": learner["id"]}), 1
        )
        assert held[0]["id"] == first["id"]
        assert held[0]["status"] == "ASSIGNED"

        refreshed = get_success_data(
            api.create_training_assignment(
                build_training_assignment(
                    learner["id"],
                    ctx["module"]["id"],
                    current["version"],
                    due_at="2026-09-20T00:00:00Z",
                ),
                hr_headers,
            ),
            201,
        )

        assert refreshed["status"] == "ASSIGNED"
        assert refreshed["due_at"] == "2026-09-20T00:00:00Z"
        assert refreshed["attempt_count"] == 0
        assert (
            get_success_data(api.get_training_assignment(first["id"], hr_headers))["status"]
            == "SUPERSEDED"
        )
        final = read_employee(api, learner["id"])
        assert final["version"] == current["version"] + 1
        assert final["training_current"] is False


class TestTwoCountersOnTwoParentsFromOneChild:
    """One follow-up action moves the case counter on creation and the plan counter on lateness."""

    def test_the_action_component_swings_down_at_the_ops_run_and_back_up_on_completion(
        self, api: ApiClient
    ) -> None:
        """Readiness travels 75.20 to 65.12 and back, because the band swings with the component.

        PRD: "The `OVERDUE` arm additionally decrements the plan's `overdue_action_count`, since the plan was being penalised for the lateness and that penalty now lifts."
        Design: Corner/cross_cutting_complexity_layers/overdue_action_count_reconciles_down_and_back_up_across_the_ops_run
        """
        ctx = setup_monitoring_case(api)
        referral = add_post_incident_action(
            api,
            ctx,
            "COUNSELING_REFERRAL",
            "hr",
            "2026-08-05T00:00:00Z",
            note="Counselling referral for the protected employee.",
        )

        assert referral["status"] == "PENDING"
        assert referral["auto_generated"] is False
        assert_case_state(read_case(api, ctx), status="MONITORING", open_action_count=1)
        opened = read_plan(api, ctx)
        assert_plan_metrics(opened, overdue_action_count=0)
        assert_readiness(opened, score=75.20, inspection_ready=False)

        assert move_clock(api, "2026-08-06T00:00:00Z") == "2026-08-06T00:00:00Z"
        counters = run_daily_sweep(api)

        assert_sweep_counters(counters, actions_overdue_count=1)
        assert read_case_action(api, ctx, referral["id"])["status"] == "OVERDUE"
        assert_case_state(read_case(api, ctx), open_action_count=1)
        late = read_plan(api, ctx)
        assert_plan_metrics(late, overdue_action_count=1)
        assert_readiness(
            late,
            subtotal=74.00,
            penalty_band="WEAK",
            penalty_points=8.88,
            score=65.12,
            inspection_ready=False,
        )

        completed = get_success_data(
            api.complete_case_action(
                referral["id"],
                build_action_completion(completion_note="Referral delivered a day late."),
                ctx["headers"]["hr_partner"],
            )
        )

        assert completed["status"] == "COMPLETED"
        assert completed["completed_at"] == "2026-08-06T00:00:00Z"
        assert completed["late_flag"] is True
        assert_case_state(read_case(api, ctx), open_action_count=0)
        reconciled = read_plan(api, ctx)
        assert_plan_metrics(reconciled, overdue_action_count=0)
        assert_readiness(
            reconciled,
            subtotal=80.00,
            penalty_band="ADEQUATE",
            penalty_points=4.80,
            score=75.20,
        )


class TestExpiryIsInclusiveOfTheClock:
    """A second before the instant nothing moves; at the instant two sweep steps fire together."""

    def test_the_refresh_falling_due_and_the_plan_falling_due_land_in_one_run(
        self, api: ApiClient
    ) -> None:
        """The comparison is at-or-before, so the completion lapses on the same instant its expiry names.

        PRD: "The nightly sweep is what causes lapses: an `ASSIGNED` assignment whose `due_at` has passed becomes `EXPIRED`, and a `COMPLETED` assignment becomes `EXPIRED` once `expires_at` is at or before the clock — the annual refresh falling due."
        Design: Corner/cross_cutting_complexity_layers/training_expiry_fires_at_exactly_the_clock_and_flips_the_readiness_flag
        """
        ctx = _single_learner_worksite(api)
        assignment_id = ctx["assignment"]["id"]
        assert ctx["assignment"]["expires_at"] == "2027-08-01T00:00:00Z"
        before = read_plan(api, ctx)
        assert_plan_state(before, status="ACTIVE", compliance_posture="OPEN")
        assert_plan_metrics(before, training_compliance_pct=100.00)
        assert_readiness(before, score=79.90, inspection_ready=True)

        assert move_clock(api, "2027-07-31T23:59:59Z") == "2027-07-31T23:59:59Z"
        early = run_daily_sweep(api)

        assert_sweep_counters(early, training_expired_count=0, plans_review_due_count=0)
        assert (
            get_success_data(
                api.get_training_assignment(assignment_id, ctx["headers"]["hr_partner"])
            )["status"]
            == "COMPLETED"
        )
        assert read_employee(api, ctx["learner"]["id"])["training_current"] is True
        unmoved = read_plan(api, ctx)
        assert_plan_state(unmoved, status="ACTIVE")
        assert_readiness(unmoved, score=79.90, inspection_ready=True)

        assert move_clock(api, "2027-08-01T00:00:00Z") == "2027-08-01T00:00:00Z"
        due = run_daily_sweep(api)

        assert_sweep_counters(
            due,
            training_expired_count=1,
            plans_review_due_count=1,
            plans_rescored_count=1,
        )
        assert (
            get_success_data(
                api.get_training_assignment(assignment_id, ctx["headers"]["hr_partner"])
            )["status"]
            == "EXPIRED"
        )
        assert read_employee(api, ctx["learner"]["id"])["training_current"] is False
        lapsed = read_plan(api, ctx)
        assert_plan_state(lapsed, status="REVIEW_DUE", compliance_posture="RESTRICTED")
        assert_plan_metrics(lapsed, training_compliance_pct=0.00)
        assert_readiness(
            lapsed,
            subtotal=60.00,
            penalty_band="WEAK",
            penalty_points=7.20,
            score=52.80,
            inspection_ready=False,
        )


class TestOneDecisionIsVisibleEverywhereAtOnce:
    """No sweep, no retry: the response body and the next four reads already agree."""

    def test_the_decide_body_and_the_four_reads_behind_it_show_the_finished_cascade(
        self, api: ApiClient
    ) -> None:
        """Report, log, worksite and plan are all already moved by the time the decide returns.

        PRD: "A single decision on a threat case can reach four levels: the case's own status moves, the underlying incident report becomes substantiated, a violent incident log entry is appended for the worksite, the worksite's rolling incident count and `high_risk_flag` move, and the worksite's active plan is pushed from `ACTIVE` to `REVIEW_DUE` with its posture tightening to `RESTRICTED` and its readiness re-evaluated against the stricter threshold."
        Design: Corner/consistency_model/decide_response_body_already_carries_every_cascaded_value
        """
        ctx = setup_deliberating_case(api)
        officer = ctx["headers"]["safety_officer"]

        decided = get_success_data(
            api.decide_threat_case(
                ctx["case"]["id"],
                build_decision("ELEVATED_RISK"),
                ctx["headers"]["threat_team_lead"],
            )
        )

        assert_case_state(decided, status="MONITORING")
        assert_risk_scores(
            decided, consensus=60.94, risk_band="HIGH", disposition="ELEVATED_RISK"
        )
        assert decided["protection_window_start"] == "2026-08-01T00:00:00Z"
        assert decided["protection_window_end"] == "2026-08-15T00:00:00Z"
        assert_protection(decided, coverage_gap_hours=336.00, protection_status="GAP")
        assert_report_dimensions(
            read_report(api, ctx),
            triage_status="SUBSTANTIATED",
            retaliation_status="NOT_ALLEGED",
        )

        entries = assert_total_count(
            api.list_log_entries(officer, {"case_id": ctx["case"]["id"]}), 1
        )

        assert entries[0]["required_element_count_present"] == 6
        assert entries[0]["perpetrator_class"] == "COWORKER"
        assert entries[0]["injury_level"] == "FIRST_AID"
        assert entries[0]["weapon_involved"] is True
        assert entries[0]["retention_expiry_date"] == "2031-07-30T14:00:00Z"
        worksite = read_worksite(api, ctx["worksite"]["id"])
        assert worksite["violent_incident_count_12mo"] == 1
        assert worksite["high_risk_flag"] is True
        plan = read_plan(api, ctx)
        assert_plan_state(
            plan, status="REVIEW_DUE", compliance_posture="RESTRICTED", inspection_ready=False
        )
        assert_plan_metrics(plan, log_completeness_pct=75.00)
        assert_readiness(
            plan, subtotal=80.00, penalty_points=4.80, score=75.20, inspection_ready=False
        )
