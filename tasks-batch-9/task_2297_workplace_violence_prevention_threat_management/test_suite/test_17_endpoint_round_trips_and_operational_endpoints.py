"""Reference-data round trips, the clock and sweep endpoints, log amendments and filtered listings."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import (
    COMPLIANCE_AUDITOR_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_auto_appended_entry_is_partial,
    assert_case_state,
    assert_log_elements_present,
    assert_plan_metrics,
    assert_plan_state,
    assert_readiness,
    assert_report_dimensions,
    assert_sweep_counters,
    assert_total_count,
    assign_training,
    build_closure,
    build_drill,
    build_log_amendment,
    build_prevention_plan,
    build_retaliation_update,
    build_training_module,
    move_clock,
    read_case,
    read_case_log_entries,
    read_employee,
    read_plan,
    read_report,
    run_daily_sweep,
    setup_active_plan,
    setup_filed_report,
    setup_monitoring_case,
    setup_training_cohort,
)

#: A cash-handling module that gates escort duty, overriding all three defaults.
CASH_MODULE = {
    "code": "WVP-CASH",
    "job_function_scope": ["CASH_HANDLING", "SECURITY"],
    "scenario_set_version": "2026.2",
    "refresh_interval_days": 180,
    "passing_score": 75,
    "required_for_escort": True,
}

#: The five regulatory elements an amendment must carry forward unchanged.
COPIED_LOG_ELEMENTS = (
    "incident_at",
    "work_area_name",
    "incident_type",
    "perpetrator_class",
    "injury_level",
)


class TestTrainingModuleRoundTrip:
    """The one entity with no state machine, so create, read and list must agree exactly."""

    def test_a_published_module_reads_back_unchanged_and_answers_both_list_shapes(
        self, api: ApiClient
    ) -> None:
        """The single read is identical to the create body, and the escort filter narrows two rows to one.

        PRD: "A `ProgramAdmin` publishes a **training module** with a `code` of 1 to 40 characters, unique across all modules, a `job_function_scope` — a non-empty array of job functions for which the module is mandatory — and a `scenario_set_version` naming the role-specific scenario pack learners will be shown."
        Design: Corner/endpoints/training_module_create_read_and_list_round_trip
        """
        ctx = setup_training_cohort(api)

        created = get_success_data(
            api.create_training_module(
                build_training_module(**CASH_MODULE), PROGRAM_ADMIN_HEADERS
            ),
            201,
        )

        assert created["code"] == "WVP-CASH"
        assert created["job_function_scope"] == ["CASH_HANDLING", "SECURITY"]
        assert created["scenario_set_version"] == "2026.2"
        assert created["refresh_interval_days"] == 180
        assert created["passing_score"] == 75
        assert created["required_for_escort"] is True

        echo = get_success_data(
            api.get_training_module(created["id"], PROGRAM_ADMIN_HEADERS)
        )

        assert echo["id"] == created["id"]
        assert echo == created

        page, meta = validate_paginated(
            api.list_training_modules(COMPLIANCE_AUDITOR_HEADERS, {"limit": 1, "offset": 1})
        )

        assert meta["total_count"] == 2
        assert meta["limit"] == 1
        assert meta["offset"] == 1
        assert meta["has_more"] is False
        assert len(page) == 1
        assert page[0]["id"] == created["id"]

        escort_only = assert_total_count(
            api.list_training_modules(PROGRAM_ADMIN_HEADERS, {"required_for_escort": "true"}),
            1,
        )

        assert escort_only[0]["id"] == created["id"]
        assert ctx["module"]["required_for_escort"] is False


class TestClockEndpointPurity:
    """Time moves on its own endpoint, and only the sweep reads the new time into rows."""

    def test_advancing_time_past_a_due_date_leaves_the_assignment_untouched(
        self, api: ApiClient
    ) -> None:
        """The clock call moves no row; the following ops run is what expires the lapsed assignment.

        PRD: "A `ProgramAdmin` may move it by supplying `current_utc`; the call changes no stored rows and returns the new clock value."
        Design: Corner/endpoints/clock_endpoint_moves_time_without_moving_any_row
        """
        ctx = setup_training_cohort(api)
        learner = ctx["rep"]
        assignment = assign_training(
            api, ctx, learner["id"], due_at="2026-08-20T00:00:00Z"
        )
        assert assignment["status"] == "ASSIGNED"
        assert assignment["attempt_count"] == 0
        before = read_employee(api, learner["id"])

        assert move_clock(api, "2026-08-21T00:00:00Z") == "2026-08-21T00:00:00Z"

        unmoved = get_success_data(
            api.get_training_assignment(assignment["id"], ctx["headers"]["hr_partner"])
        )
        assert unmoved["status"] == "ASSIGNED"
        after_clock = read_employee(api, learner["id"])
        assert after_clock["training_current"] is False
        assert after_clock["version"] == before["version"]

        counters = run_daily_sweep(api)

        assert_sweep_counters(counters, strict=True, training_expired_count=1)
        lapsed = get_success_data(
            api.get_training_assignment(assignment["id"], ctx["headers"]["hr_partner"])
        )
        assert lapsed["status"] == "EXPIRED"
        assert read_employee(api, learner["id"])["training_current"] is False


class TestSweepStepOrder:
    """Steps 7 and 8 in one call mean a plan is rescored against the bar it just earned."""

    def test_a_plan_falling_due_is_rescored_against_the_restricted_threshold_in_the_same_sweep(
        self, api: ApiClient
    ) -> None:
        """The score never moves, yet inspection_ready flips because the threshold rose from 75.00 to 85.00.

        PRD: "Because steps 7 and 8 never reorder, a plan that falls due in step 7 is always rescored in step 8 against the stricter `RESTRICTED` readiness threshold within the same sweep."
        Design: Corner/endpoints/daily_run_step_order_rescores_a_newly_review_due_plan_against_the_restricted_threshold
        """
        ctx = setup_active_plan(api)
        drill = get_success_data(
            api.create_drill(
                build_drill(ctx["plan"]["id"], scheduled_at="2026-08-10T00:00:00Z"),
                ctx["headers"]["safety_officer"],
            ),
            201,
        )
        before = read_plan(api, ctx)
        assert_plan_state(before, status="ACTIVE", compliance_posture="OPEN")
        assert_readiness(before, score=79.90, inspection_ready=True)

        assert move_clock(api, "2027-08-01T00:00:00Z") == "2027-08-01T00:00:00Z"
        counters = run_daily_sweep(api)

        assert_sweep_counters(
            counters,
            strict=True,
            drills_missed_count=1,
            plans_review_due_count=1,
            plans_rescored_count=1,
        )
        missed = get_success_data(
            api.get_drill(drill["id"], ctx["headers"]["safety_officer"])
        )
        assert missed["status"] == "MISSED"
        assert missed["executed_at"] is None
        assert missed["participation_pct"] is None
        assert missed["credited"] is False
        after = read_plan(api, ctx)
        assert_plan_state(after, status="REVIEW_DUE", compliance_posture="RESTRICTED")
        assert_plan_metrics(after, drills_completed_12mo=0)
        assert_readiness(
            after,
            subtotal=85.00,
            penalty_band="ADEQUATE",
            penalty_points=5.10,
            score=79.90,
            inspection_ready=False,
        )


class TestLogAmendmentEndpoint:
    """Amendment appends a successor row, and the close gate reads only the live entries."""

    def test_the_amendment_that_completes_the_register_unblocks_the_refused_close(
        self, api: ApiClient
    ) -> None:
        """Six elements refuse the close, the successor carries eight, and the identical call then passes.

        PRD: "A new entry is created with `supersedes_entry_id` pointing at the target, the target's `superseded_flag` becomes true, and `required_element_count_present` is recomputed on the new entry from the eight elements now present — which is how a six-element entry becomes an eight-element one."
        Design: Corner/endpoints/log_amendment_appends_a_successor_and_unblocks_case_close
        """
        ctx = setup_monitoring_case(api)
        lead_headers = ctx["headers"]["threat_team_lead"]
        officer = ctx["headers"]["safety_officer"]
        original = read_case_log_entries(api, ctx)[0]
        assert_auto_appended_entry_is_partial(original)
        assert_case_state(read_case(api, ctx), status="MONITORING", open_action_count=0)

        refused = api.close_threat_case(
            ctx["case"]["id"],
            build_closure(
                closure_summary="Monitoring complete; closing before the log is amended."
            ),
            lead_headers,
        )

        validate_error(refused, ApiErrorId.LOG_ENTRY_REQUIRED_ELEMENT_MISSING, 409)
        assert (
            refused.json()["data"]["error_id"] != ApiErrorId.OPEN_ACTIONS_BLOCK_CLOSE
        )

        successor = get_success_data(
            api.amend_log_entry(original["id"], build_log_amendment(), officer), 201
        )

        assert successor["supersedes_entry_id"] == original["id"]
        assert_log_elements_present(successor, 8)
        for element in COPIED_LOG_ELEMENTS:
            assert successor[element] == original[element]
        assert successor["perpetrator_class"] == "COWORKER"
        superseded = get_success_data(api.get_log_entry(original["id"], officer))
        assert_log_elements_present(superseded, 6)
        assert superseded["superseded_flag"] is True
        chained = assert_total_count(
            api.list_log_entries(officer, {"supersedes_entry_id": original["id"]}), 1
        )
        assert chained[0]["id"] == successor["id"]
        plan = read_plan(api, ctx)
        assert_plan_metrics(plan, log_completeness_pct=100.00)
        assert_readiness(plan, score=79.90, inspection_ready=False)

        closed = get_success_data(
            api.close_threat_case(
                ctx["case"]["id"],
                build_closure(closure_summary="Log amended to eight elements; case closed."),
                lead_headers,
            )
        )

        assert_case_state(closed, status="CLOSED")
        assert closed["protection_status"] == "NOT_APPLICABLE"


class TestPlanListingOnADerivedFlag:
    """A flag no client ever writes is still a first-class equality filter."""

    def test_the_two_plans_of_one_worksite_are_separated_by_the_readiness_filter(
        self, api: ApiClient
    ) -> None:
        """The ACTIVE plan answers the true filter, the FROZEN draft the false one, and both the unfiltered list.

        PRD: "It is always false whenever `compliance_posture` is `FROZEN`, regardless of the score."
        Design: Corner/endpoints/prevention_plan_list_filters_on_the_derived_inspection_ready_flag
        """
        ctx = setup_active_plan(api)
        worksite_id = ctx["worksite"]["id"]
        active = read_plan(api, ctx)
        assert_plan_state(active, status="ACTIVE", compliance_posture="OPEN")
        assert_readiness(active, score=79.90, inspection_ready=True)

        draft = get_success_data(
            api.create_prevention_plan(
                build_prevention_plan(worksite_id, effective_date="2026-09-01T00:00:00Z"),
                ctx["headers"]["safety_officer"],
            ),
            201,
        )

        assert draft["plan_revision"] == 2
        assert_plan_state(draft, status="DRAFT", compliance_posture="FROZEN")
        assert_plan_metrics(draft, hazard_coverage_pct=0.00)
        assert_readiness(
            draft,
            subtotal=55.00,
            penalty_band="WEAK",
            penalty_points=0.00,
            score=55.00,
            inspection_ready=False,
        )

        ready = assert_total_count(
            api.list_prevention_plans(
                COMPLIANCE_AUDITOR_HEADERS,
                {"worksite_id": worksite_id, "inspection_ready": "true"},
            ),
            1,
        )
        not_ready = assert_total_count(
            api.list_prevention_plans(
                COMPLIANCE_AUDITOR_HEADERS,
                {"worksite_id": worksite_id, "inspection_ready": "false"},
            ),
            1,
        )
        everything, meta = validate_paginated(
            api.list_prevention_plans(
                COMPLIANCE_AUDITOR_HEADERS, {"worksite_id": worksite_id}
            )
        )

        assert ready[0]["id"] == ctx["plan"]["id"]
        assert ready[0]["status"] == "ACTIVE"
        assert not_ready[0]["id"] == draft["id"]
        assert not_ready[0]["status"] == "DRAFT"
        assert meta["total_count"] == 2
        assert meta["limit"] == 10
        assert meta["has_more"] is False
        assert {row["id"] for row in everything} == {ctx["plan"]["id"], draft["id"]}
        assert read_plan(api, ctx)["version"] == active["version"]


class TestRetaliationActionDiscriminator:
    """One endpoint, four transitions, and a different actor rule on each."""

    def test_the_reporter_alone_may_allege_and_hr_alone_drives_the_review(
        self, api: ApiClient
    ) -> None:
        """The subject is refused as a non-owner, the replayed allegation as a bad state, and triage never moves.

        PRD: "When the caller's role is `Employee`, their `X-User-ID` must equal the report's `reporter_employee_id` or the request is refused with `ERR_NOT_RESOURCE_OWNER`; an `HRPartner` may raise the allegation on the claimant's behalf."
        Design: Corner/endpoints/retaliation_update_action_discriminator_drives_four_transitions
        """
        ctx = setup_filed_report(api)
        report_id = ctx["report"]["id"]
        hr_headers = ctx["headers"]["hr_partner"]
        assert_report_dimensions(
            ctx["report"], triage_status="NEW", retaliation_status="NOT_ALLEGED"
        )

        intruder = api.create_retaliation_update(
            report_id,
            build_retaliation_update(
                "ALLEGE", statement="I was moved to nights after I filed the report."
            ),
            ctx["headers"]["subject"],
        )

        validate_error(intruder, ApiErrorId.NOT_RESOURCE_OWNER, 403)
        assert_report_dimensions(read_report(api, ctx), retaliation_status="NOT_ALLEGED")

        alleged = get_success_data(
            api.create_retaliation_update(
                report_id,
                build_retaliation_update(
                    "ALLEGE",
                    statement="My shift was changed the day after I filed this report.",
                ),
                ctx["headers"]["employee"],
            )
        )

        assert_report_dimensions(alleged, retaliation_status="ALLEGED")
        assert alleged["retaliation_claimant_employee_id"] == ctx["rep"]["id"]

        replayed = api.create_retaliation_update(
            report_id,
            build_retaliation_update(
                "ALLEGE", statement="Repeating my allegation because nothing has happened."
            ),
            ctx["headers"]["employee"],
        )

        validate_error(replayed, ApiErrorId.RETALIATION_INVALID_STATE, 409)
        assert replayed.json()["data"]["error_id"] != ApiErrorId.NOT_RESOURCE_OWNER

        reviewing = get_success_data(
            api.create_retaliation_update(
                report_id,
                build_retaliation_update(
                    "OPEN_REVIEW", statement="HR is reviewing the schedule change."
                ),
                hr_headers,
            )
        )
        substantiated = get_success_data(
            api.create_retaliation_update(
                report_id,
                build_retaliation_update(
                    "SUBSTANTIATE",
                    statement="Schedule change was retaliatory; hold is permanent.",
                ),
                hr_headers,
            )
        )

        assert_report_dimensions(reviewing, retaliation_status="UNDER_REVIEW")
        assert_report_dimensions(
            substantiated, triage_status="NEW", retaliation_status="SUBSTANTIATED"
        )
        assert substantiated["retaliation_claimant_employee_id"] == ctx["rep"]["id"]
