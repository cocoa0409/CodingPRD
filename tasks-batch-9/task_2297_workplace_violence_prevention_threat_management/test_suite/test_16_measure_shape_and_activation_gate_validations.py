"""Case-action shape rules, the training and drill bounds, and the two gates that guard activation."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    ApiClient,
    ApiErrorId,
    add_hazard_assessment,
    assert_case_state,
    assert_plan_metrics,
    assert_plan_state,
    assert_protection,
    assert_total_count,
    assign_training,
    build_drill_execution,
    build_hazard_assessment,
    build_plan_activation,
    build_post_incident_action,
    build_protective_action,
    build_training_assignment,
    build_training_completion,
    complete_training,
    make_employee_headers,
    read_case,
    read_employee,
    read_plan,
    setup_draft_plan,
    setup_drilled_plan,
    setup_employee,
    setup_monitoring_case,
    setup_programme,
    setup_screened_plan,
    setup_submitted_plan,
    setup_training_cohort,
    setup_work_area,
    setup_worksite,
)

#: A second area on the same worksite, benign on every exposure flag.
BREAK_ROOM = {
    "name": "Break Room",
    "job_function": "ADMIN",
    "public_access_flag": False,
    "lone_worker_flag": False,
    "night_shift_flag": False,
    "occupancy_cap": 6,
}

#: The only area of the neighbouring worksite, which no North Plant plan may assess.
DEPOT_DOCK = {
    "name": "Depot Dock",
    "job_function": "WAREHOUSE",
    "public_access_flag": False,
    "lone_worker_flag": False,
    "night_shift_flag": False,
    "occupancy_cap": 10,
}


class TestIntervalShapePrecedence:
    """A reversed interval is refused before any window or merge arithmetic sees it."""

    def test_a_backwards_measure_reports_the_interval_and_not_the_window(
        self, api: ApiClient
    ) -> None:
        """The same dates in the right order prove the window rule was live behind the shape check.

        PRD: "Interval shape is next, and it is checked before any overlap or window arithmetic so that a reversed interval never reaches the merge logic."
        Design: Corner/validations/reversed_protective_interval_returns_invalid_interval_before_overlap_rules
        """
        ctx = setup_monitoring_case(api)
        coordinator = ctx["headers"]["security_coordinator"]

        backwards = api.create_case_action(
            build_protective_action(
                ctx["case"]["id"],
                "SCHEDULE_CHANGE",
                ctx["subj"]["id"],
                "2026-09-10T00:00:00Z",
                "2026-09-05T00:00:00Z",
                note="Reversed interval wholly after the window.",
            ),
            coordinator,
        )

        validate_error(backwards, ApiErrorId.INVALID_INTERVAL, 422)
        assert (
            backwards.json()["data"]["error_id"]
            != ApiErrorId.MEASURE_OUTSIDE_PROTECTION_WINDOW
        )

        forwards = api.create_case_action(
            build_protective_action(
                ctx["case"]["id"],
                "SCHEDULE_CHANGE",
                ctx["subj"]["id"],
                "2026-09-05T00:00:00Z",
                "2026-09-10T00:00:00Z",
                note="Well-formed interval, still wholly after the window.",
            ),
            coordinator,
        )

        validate_error(forwards, ApiErrorId.MEASURE_OUTSIDE_PROTECTION_WINDOW, 409)
        assert_protection(
            read_case(api, ctx), coverage_gap_hours=336.00, protection_status="GAP"
        )
        assert_total_count(
            api.list_case_actions(coordinator, {"case_id": ctx["case"]["id"]}), 0
        )

    def test_the_three_shape_rules_of_the_merged_action_entity_each_answer_separately(
        self, api: ApiClient
    ) -> None:
        """An interval on a follow-up, a crossed class pairing and a restriction with no area all fail apart.

        PRD: "A `PROTECTIVE` action must carry both `starts_at` and `ends_at` with `starts_at` strictly earlier than `ends_at`; a `POST_INCIDENT` action must carry `due_at` and must carry neither `starts_at` nor `ends_at`."
        Design: Corner/validations/case_action_interval_and_field_shape_violations_rejected
        """
        ctx = setup_monitoring_case(api)
        coordinator = ctx["headers"]["security_coordinator"]

        dated_follow_up = api.create_case_action(
            build_post_incident_action(
                ctx["case"]["id"],
                "COUNSELING_REFERRAL",
                ctx["hr"]["id"],
                "2026-08-10T00:00:00Z",
                starts_at="2026-08-05T00:00:00Z",
                note="Post-incident action carrying an interval.",
            ),
            ctx["headers"]["hr_partner"],
        )
        crossed_pairing = api.create_case_action(
            build_protective_action(
                ctx["case"]["id"],
                "COUNSELING_REFERRAL",
                ctx["subj"]["id"],
                "2026-08-05T00:00:00Z",
                "2026-08-06T00:00:00Z",
                note="Counselling referral declared as a protective measure.",
            ),
            coordinator,
        )
        arealess_restriction = api.create_case_action(
            build_protective_action(
                ctx["case"]["id"],
                "ACCESS_RESTRICTION",
                ctx["subj"]["id"],
                "2026-08-05T00:00:00Z",
                "2026-08-06T00:00:00Z",
                note="Access restriction with no work area named.",
            ),
            coordinator,
        )

        validate_error(dated_follow_up, ApiErrorId.INVALID_INTERVAL, 422)
        validate_error(crossed_pairing, ApiErrorId.ACTION_TYPE_CLASS_MISMATCH, 422)
        validate_error(arealess_restriction, ApiErrorId.ACTION_FIELD_MISSING, 422)
        case = read_case(api, ctx)
        assert_case_state(case, status="MONITORING", open_action_count=0)
        assert_protection(case, coverage_gap_hours=336.00, protection_status="GAP")
        assert_total_count(
            api.list_case_actions(coordinator, {"case_id": ctx["case"]["id"]}), 0
        )


class TestTrainingAttemptAccounting:
    """A refused completion still writes, because the attempt counter records the try."""

    def test_a_failing_score_counts_as_an_attempt_and_the_passing_boundary_completes(
        self, api: ApiClient
    ) -> None:
        """Seventy-nine is refused but counted; exactly eighty passes and pins the scenario pack.

        PRD: "The submitted `score` must be at least the module's `passing_score`, or the request is refused with `ERR_TRAINING_SCORE_BELOW_PASSING` — but a failed attempt is not free: `attempt_count` counts every completion call the assignment has seen, whether accepted or rejected for score, and the row stays `ASSIGNED` so the learner may try again."
        Design: Corner/validations/training_score_below_passing_leaves_the_assignment_assigned
        """
        ctx = setup_training_cohort(api)
        learner = ctx["rep"]
        assignment = assign_training(
            api, ctx, learner["id"], due_at="2026-08-20T00:00:00Z"
        )
        assert assignment["status"] == "ASSIGNED"
        assert assignment["attempt_count"] == 0

        failed = api.complete_training_assignment(
            assignment["id"],
            build_training_completion(79),
            make_employee_headers(learner["id"]),
        )

        validate_error(failed, ApiErrorId.TRAINING_SCORE_BELOW_PASSING, 409)
        after_failure = get_success_data(
            api.get_training_assignment(assignment["id"], ctx["headers"]["hr_partner"])
        )
        assert after_failure["status"] == "ASSIGNED"
        assert after_failure["completed_at"] is None
        assert after_failure["expires_at"] is None
        assert after_failure["attempt_count"] == 1
        assert read_employee(api, learner["id"])["training_current"] is False

        passed = complete_training(api, ctx, assignment["id"], learner["id"], score=80)

        assert passed["status"] == "COMPLETED"
        assert passed["completed_at"] == "2026-08-01T00:00:00Z"
        assert passed["expires_at"] == "2027-08-01T00:00:00Z"
        assert passed["scenario_set_version"] == "2026.1"
        assert passed["attempt_count"] == 2
        assert read_employee(api, learner["id"])["training_current"] is True

    def test_a_security_worker_cannot_be_given_the_admin_module(self, api: ApiClient) -> None:
        """Both keys resolve and the version guard matches, yet the pair is incoherent and nothing is bumped.

        PRD: "The learner's `job_function` must be one of the values in the module's `job_function_scope`; assigning a warehouse worker a patient-care module is refused with `ERR_MODULE_SCOPE_MISMATCH`."
        Design: Corner/validations/module_scope_mismatch_on_training_assignment_rejected
        """
        ctx = setup_training_cohort(api)
        guard = setup_employee(
            api,
            ctx["worksite"]["id"],
            ctx["work_area"]["id"],
            full_name="Sam Okoye",
            job_function="SECURITY",
        )

        response = api.create_training_assignment(
            build_training_assignment(
                guard["id"],
                ctx["module"]["id"],
                guard["version"],
                due_at="2026-08-20T00:00:00Z",
            ),
            ctx["headers"]["hr_partner"],
        )

        validate_error(response, ApiErrorId.MODULE_SCOPE_MISMATCH, 409)
        assert response.json()["data"]["error_id"] != ApiErrorId.STALE_EMPLOYEE_VERSION
        stored = read_employee(api, guard["id"])
        assert stored["version"] == guard["version"]
        assert stored["training_current"] is False
        assert_total_count(
            api.list_training_assignments(
                ctx["headers"]["hr_partner"], {"employee_id": guard["id"]}
            ),
            0,
        )


class TestDrillParticipationBounds:
    """Both halves of the bound protect the participation denominator with one code."""

    def test_an_oversized_turnout_and_an_oversized_finding_list_are_both_refused(
        self, api: ApiClient
    ) -> None:
        """Twenty-one of twenty and fifty-one findings both leave the drill SCHEDULED with nulls.

        PRD: "Execution records a `participant_count` between 0 and the worksite's `employee_count` and a `findings_count` between 0 and 50; a participant count above the declared headcount, or more than 50 findings, is refused with `ERR_PARTICIPANT_COUNT_EXCEEDS_HEADCOUNT`, which is what protects the participation denominator."
        Design: Corner/validations/drill_participant_count_above_headcount_rejected
        """
        ctx = setup_drilled_plan(api)
        officer = ctx["headers"]["safety_officer"]

        validate_error(
            api.execute_drill(
                ctx["drill_one"]["id"], build_drill_execution(21, findings_count=1), officer
            ),
            ApiErrorId.PARTICIPANT_COUNT_EXCEEDS_HEADCOUNT,
            422,
        )
        validate_error(
            api.execute_drill(
                ctx["drill_one"]["id"], build_drill_execution(12, findings_count=51), officer
            ),
            ApiErrorId.PARTICIPANT_COUNT_EXCEEDS_HEADCOUNT,
            422,
        )

        drill = get_success_data(api.get_drill(ctx["drill_one"]["id"], officer))
        assert drill["status"] == "SCHEDULED"
        assert drill["executed_at"] is None
        assert drill["participant_count"] is None
        assert drill["findings_count"] is None
        assert drill["participation_pct"] is None
        assert drill["credited"] is False
        assert_plan_metrics(read_plan(api, ctx), drills_completed_12mo=0)


class TestActivationCoverageGate:
    """The gate is an aggregate over sibling assessments, not a field the plan carries."""

    def test_an_unassessed_second_area_blocks_activation_until_it_is_screened(
        self, api: ApiClient
    ) -> None:
        """Fifty percent coverage refuses the approval; the second assessment lets the identical call through.

        PRD: "Second, `hazard_coverage_pct` must equal exactly 100.00 — every work area of the worksite must carry a live hazard assessment — or the request is refused with `ERR_HAZARD_COVERAGE_INCOMPLETE`."
        Design: Corner/validations/hazard_coverage_incomplete_blocks_activation
        """
        ctx = setup_programme(api)
        break_room = setup_work_area(api, ctx["worksite"]["id"], **BREAK_ROOM)
        ctx = setup_draft_plan(api, ctx)
        ctx = setup_screened_plan(api, ctx)
        ctx = setup_submitted_plan(api, ctx)
        before = read_plan(api, ctx)
        assert_plan_state(before, status="IN_REVIEW", compliance_posture="FROZEN")
        assert_plan_metrics(
            before, hazard_coverage_pct=50.00, training_compliance_pct=100.00
        )

        refused = api.activate_prevention_plan(
            ctx["plan"]["id"],
            build_plan_activation(
                activation_note="Approving with the break room still unassessed."
            ),
            ctx["headers"]["site_manager"],
        )

        validate_error(refused, ApiErrorId.HAZARD_COVERAGE_INCOMPLETE, 409)
        assert (
            refused.json()["data"]["error_id"]
            != ApiErrorId.TRAINING_COMPLIANCE_BELOW_THRESHOLD
        )
        add_hazard_assessment(api, ctx, break_room["id"])
        covered = read_plan(api, ctx)
        assert_plan_metrics(covered, hazard_coverage_pct=100.00)
        assert_plan_state(covered, status="IN_REVIEW")

        activated = get_success_data(
            api.activate_prevention_plan(
                ctx["plan"]["id"],
                build_plan_activation(
                    activation_note="Both areas now assessed; approved."
                ),
                ctx["headers"]["site_manager"],
            )
        )

        assert_plan_state(activated, status="ACTIVE", compliance_posture="OPEN")
        assert_plan_metrics(activated, unmitigated_hazard_count=1)


class TestVersionGuardPrecedence:
    """The optimistic guard outranks the cross-aggregate rule on the same request."""

    def test_the_stale_token_answers_before_the_cross_worksite_area_is_noticed(
        self, api: ApiClient
    ) -> None:
        """A stale version against a foreign work area returns 412; the retry surfaces the 409 behind it.

        PRD: "These run ahead of every state and business rule on the two endpoints that carry them, so a stale version against a plan in the wrong state still returns 412."
        Design: Corner/validations/stale_plan_version_outranks_the_work_area_worksite_mismatch_check
        """
        ctx = setup_programme(api)
        depot = setup_worksite(api, name="South Depot")
        depot_dock = setup_work_area(api, depot["id"], **DEPOT_DOCK)
        ctx = setup_draft_plan(api, ctx)
        stale_version = ctx["plan"]["version"]
        add_hazard_assessment(api, ctx)
        current = read_plan(api, ctx)
        assert current["version"] == stale_version + 1

        stale = api.create_hazard_assessment(
            build_hazard_assessment(
                ctx["plan"]["id"],
                depot_dock["id"],
                stale_version,
                reported_incident_count=2,
                proximity_factor="LOW",
            ),
            ctx["headers"]["safety_officer"],
        )

        validate_error(stale, ApiErrorId.STALE_PLAN_VERSION, 412)
        assert (
            stale.json()["data"]["error_id"] != ApiErrorId.WORK_AREA_WORKSITE_MISMATCH
        )

        retried = api.create_hazard_assessment(
            build_hazard_assessment(
                ctx["plan"]["id"],
                depot_dock["id"],
                current["version"],
                reported_incident_count=2,
                proximity_factor="LOW",
            ),
            ctx["headers"]["safety_officer"],
        )

        validate_error(retried, ApiErrorId.WORK_AREA_WORKSITE_MISMATCH, 409)
        final = read_plan(api, ctx)
        assert final["version"] == current["version"]
        assert_plan_metrics(final, hazard_coverage_pct=100.00)
