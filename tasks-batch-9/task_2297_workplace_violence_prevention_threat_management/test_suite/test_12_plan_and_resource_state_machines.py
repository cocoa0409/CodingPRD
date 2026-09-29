"""Plan, training, seat, escort and drill transitions, including the ones no endpoint drives directly."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    ApiClient,
    ApiErrorId,
    PROGRAM_ADMIN_HEADERS,
    add_escort_action,
    assert_case_action,
    assert_case_state,
    assert_escort_ledger,
    assert_plan_metrics,
    assert_plan_state,
    assert_protection,
    assert_seat_ballot,
    assert_seat_ballot_cleared,
    assert_sweep_counters,
    assert_total_count,
    assert_two_decimal_value,
    assign_training,
    build_closure,
    build_plan_activation,
    build_plan_revision_return,
    build_prevention_plan,
    build_separation,
    complete_training,
    move_clock,
    read_case,
    read_case_action,
    read_employee,
    read_plan,
    read_work_area,
    run_daily_sweep,
    setup_active_plan,
    setup_deliberating_case,
    setup_draft_plan,
    setup_drilled_plan,
    setup_monitoring_case_with_escort,
    setup_screened_plan,
    setup_submitted_plan,
    setup_training_cohort,
)


def _add_ready_revision(api: ApiClient, ctx):
    """Draft, screen and submit one more plan for the same worksite, ready to activate."""
    ctx = setup_draft_plan(api, ctx)
    ctx = setup_screened_plan(api, ctx)
    return setup_submitted_plan(api, ctx)


class TestPlanReturnAndActivationGuard:
    """The two transitions out of IN_REVIEW, and what the DRAFT state refuses."""

    def test_returning_a_plan_for_revision_clears_the_submitter_stamp(
        self, api: ApiClient
    ) -> None:
        """The only transition whose side effect is a field clear takes the segregation baseline back to null.

        PRD: "A `SiteManager` may push an `IN_REVIEW` plan back with a mandatory `revision_reason`, returning it to `DRAFT` and **clearing** `submitted_by_employee_id` so that the next submission re-stamps the segregation baseline from scratch."
        Design: Corner/state_machines/return_for_revision_clears_the_submitter_stamp
        """
        ctx = setup_submitted_plan(api)
        assert_plan_state(ctx["plan"], status="IN_REVIEW", compliance_posture="FROZEN")
        assert ctx["plan"]["submitted_by_employee_id"] == ctx["so"]["id"]

        returned = get_success_data(
            api.return_prevention_plan_for_revision(
                ctx["plan"]["id"],
                build_plan_revision_return(
                    revision_reason="The hazard narrative omits the night-shift lone-worker controls."
                ),
                ctx["headers"]["site_manager"],
            )
        )

        assert_plan_state(
            returned, status="DRAFT", compliance_posture="FROZEN", inspection_ready=False
        )
        assert returned["submitted_by_employee_id"] is None
        stored = read_plan(api, ctx)
        assert stored["submitted_by_employee_id"] is None
        assert stored["activated_by_employee_id"] is None
        assert stored["activated_at"] is None

    def test_a_draft_plan_refuses_both_activation_and_return(self, api: ApiClient) -> None:
        """DRAFT to ACTIVE is undeclared, so the state check answers before the coverage gate can.

        PRD: "Activation is otherwise rejected with `ERR_PLAN_INVALID_STATE` when the plan is in any state other than `IN_REVIEW`."
        Design: Corner/state_machines/activate_a_draft_plan_rejected
        """
        ctx = setup_draft_plan(api)
        plan = read_plan(api, ctx)
        assert_plan_state(plan, status="DRAFT")
        assert_plan_metrics(plan, hazard_coverage_pct=0.00)

        activation = api.activate_prevention_plan(
            plan["id"],
            build_plan_activation(activation_note="Trying to activate straight from draft."),
            ctx["headers"]["site_manager"],
        )
        validate_error(activation, ApiErrorId.PLAN_INVALID_STATE, 409)
        assert (
            activation.json()["data"]["error_id"] != ApiErrorId.HAZARD_COVERAGE_INCOMPLETE
        )
        validate_error(
            api.return_prevention_plan_for_revision(
                plan["id"],
                build_plan_revision_return(
                    revision_reason="Trying to return a plan that was never submitted."
                ),
                ctx["headers"]["site_manager"],
            ),
            ApiErrorId.PLAN_INVALID_STATE,
            409,
        )

        after = read_plan(api, ctx)
        assert_plan_state(after, status="DRAFT")
        assert after["activated_by_employee_id"] is None


class TestActivationSupersedeCascade:
    """One activation moves a sibling row, but only a sibling in the right state."""

    def test_the_incumbent_plan_is_pushed_to_superseded_and_frozen(
        self, api: ApiClient
    ) -> None:
        """Revision 2 goes live, revision 1 freezes, and the front desk score re-resolves to the live plan.

        PRD: "Every *other* plan for the same worksite whose `status` is `ACTIVE` or `REVIEW_DUE` transitions to `SUPERSEDED`; because a superseded plan's `compliance_posture` becomes `FROZEN`, its `inspection_ready` becomes false and cases still pointing at it can no longer receive case actions, which surface as `ERR_PLAN_POSTURE_FROZEN`."
        Design: Corner/state_machines/activating_a_second_plan_supersedes_the_prior_active_plan
        """
        ctx = setup_active_plan(api)
        incumbent_id = ctx["plan"]["id"]
        first_assessment_id = ctx["hazard_assessment"]["id"]
        ctx = _add_ready_revision(api, ctx)
        assert ctx["plan"]["plan_revision"] == 2
        assert_plan_state(ctx["plan"], status="IN_REVIEW")

        activated = get_success_data(
            api.activate_prevention_plan(
                ctx["plan"]["id"],
                build_plan_activation(
                    activation_note="Revision 2 replaces revision 1 from today."
                ),
                ctx["headers"]["site_manager"],
            )
        )

        assert_plan_state(activated, status="ACTIVE", compliance_posture="OPEN")
        assert activated["plan_revision"] == 2
        assert activated["activated_by_employee_id"] == ctx["sm"]["id"]
        assert activated["activated_at"] == "2026-08-01T00:00:00Z"
        assert activated["review_due_date"] == "2027-08-01T00:00:00Z"
        incumbent = read_plan(api, ctx, incumbent_id)
        assert_plan_state(
            incumbent,
            status="SUPERSEDED",
            compliance_posture="FROZEN",
            inspection_ready=False,
        )
        area = read_work_area(api, ctx["work_area"]["id"])
        assert_two_decimal_value(area["current_hazard_score"], 64.00, "current_hazard_score")
        first_assessment = get_success_data(
            api.get_hazard_assessment(first_assessment_id, ctx["headers"]["safety_officer"])
        )
        assert first_assessment["status"] == "SCREENING"

    def test_a_draft_sibling_is_left_where_it_stands(self, api: ApiClient) -> None:
        """The cascade reads the sibling's state, so revision 3 stays DRAFT with nothing rescored into readiness.

        PRD: "Every *other* plan for the same worksite whose `status` is `ACTIVE` or `REVIEW_DUE` transitions to `SUPERSEDED`; because a superseded plan's `compliance_posture` becomes `FROZEN`, its `inspection_ready` becomes false and cases still pointing at it can no longer receive case actions, which surface as `ERR_PLAN_POSTURE_FROZEN`."
        Design: Corner/state_machines/only_active_and_review_due_sibling_plans_are_superseded
        """
        ctx = setup_active_plan(api)
        incumbent_id = ctx["plan"]["id"]
        ctx = _add_ready_revision(api, ctx)
        third = get_success_data(
            api.create_prevention_plan(
                build_prevention_plan(ctx["worksite"]["id"]),
                ctx["headers"]["safety_officer"],
            )
        )
        assert third["plan_revision"] == 3

        activated = get_success_data(
            api.activate_prevention_plan(
                ctx["plan"]["id"],
                build_plan_activation(
                    activation_note="Revision 2 goes live; revision 3 is still being drafted."
                ),
                ctx["headers"]["site_manager"],
            )
        )

        assert_plan_state(activated, status="ACTIVE")
        assert_plan_state(read_plan(api, ctx, incumbent_id), status="SUPERSEDED")
        untouched = read_plan(api, ctx, third["id"])
        assert_plan_state(
            untouched,
            status="DRAFT",
            compliance_posture="FROZEN",
            inspection_ready=False,
        )
        assert untouched["plan_revision"] == 3
        assert_plan_metrics(untouched, hazard_coverage_pct=0.00)
        assert_total_count(
            api.list_prevention_plans(
                ctx["headers"]["safety_officer"],
                {"worksite_id": ctx["worksite"]["id"], "status": "SUPERSEDED"},
            ),
            1,
        )


class TestTrainingRefresh:
    """The assignment create doubles as the annual refresh, so it supersedes its predecessor."""

    def test_the_refresh_supersedes_the_completed_assignment_and_bumps_the_learner(
        self, api: ApiClient
    ) -> None:
        """A second assignment for the same pair pushes the first to SUPERSEDED and drops training_current.

        PRD: "The same call is also the **annual refresh**: any prior assignment for the same learner and module — whether `ASSIGNED`, `COMPLETED` or `EXPIRED` — becomes `SUPERSEDED` and stops counting toward `training_compliance_pct`, and the create increments the learner's `Employee` `version` by one."
        Design: Corner/state_machines/training_refresh_create_supersedes_the_prior_assignment
        """
        ctx = setup_training_cohort(api)
        learner = ctx["rep"]
        first = assign_training(api, ctx, learner["id"])
        first = complete_training(api, ctx, first["id"], learner["id"])
        assert first["status"] == "COMPLETED"
        assert first["expires_at"] == "2027-08-01T00:00:00Z"
        before = read_employee(api, learner["id"])
        assert before["training_current"] is True

        refresh = assign_training(
            api, ctx, learner["id"], due_at="2027-08-15T00:00:00Z"
        )

        assert refresh["status"] == "ASSIGNED"
        assert refresh["attempt_count"] == 0
        assert refresh["assigned_at"] == "2026-08-01T00:00:00Z"
        superseded = get_success_data(
            api.get_training_assignment(first["id"], ctx["headers"]["hr_partner"])
        )
        assert superseded["status"] == "SUPERSEDED"
        after = read_employee(api, learner["id"])
        assert after["version"] == before["version"] + 1
        assert after["training_current"] is False
        assert_total_count(
            api.list_training_assignments(
                ctx["headers"]["hr_partner"],
                {"employee_id": learner["id"], "module_id": ctx["module"]["id"]},
            ),
            2,
        )


class TestSeparationReachesForeignAggregates:
    """One HR write revokes an escort it never named and recuses a seat it never mentioned."""

    def test_separating_the_escort_reopens_the_window_and_generates_a_review(
        self, api: ApiClient
    ) -> None:
        """The revoked escort credits all 20160 minutes back, the whole window becomes a gap and closure is blocked.

        PRD: "First, every security-escort action naming the departing worker as escort whose `status` is `SCHEDULED` or `ACTIVE` becomes `REVOKED`, crediting `escort_committed_minutes` back until it reaches 0."
        Design: Corner/state_machines/separating_the_escort_revokes_the_escort_and_appends_safety_plan_review
        """
        ctx = setup_monitoring_case_with_escort(api)
        escort_action = add_escort_action(
            api, ctx, "2026-08-01T00:00:00Z", "2026-08-15T00:00:00Z"
        )
        assert_case_action(
            escort_action, status="SCHEDULED", duration_minutes=20160, auto_generated=False
        )
        assert_escort_ledger(read_employee(api, ctx["escort"]["id"]), 20160)
        assert_protection(
            read_case(api, ctx), coverage_gap_hours=0.00, protection_status="COVERED"
        )

        separated = get_success_data(
            api.separate_employee(
                ctx["escort"]["id"],
                build_separation(separation_reason="Escort resigned with immediate effect."),
                ctx["headers"]["hr_partner"],
            )
        )

        assert separated["employment_status"] == "SEPARATED"
        revoked = read_case_action(api, ctx, escort_action["id"])
        assert_case_action(revoked, status="REVOKED")
        assert revoked["revoked_at"] == "2026-08-01T00:00:00Z"
        assert_escort_ledger(read_employee(api, ctx["escort"]["id"]), 0)
        case = read_case(api, ctx)
        assert_protection(case, coverage_gap_hours=336.00, protection_status="GAP")
        assert_case_state(case, status="MONITORING", open_action_count=1)
        assert_total_count(
            api.list_case_actions(
                ctx["headers"]["security_coordinator"],
                {
                    "case_id": ctx["case"]["id"],
                    "action_type": "SAFETY_PLAN_REVIEW",
                    "auto_generated": "true",
                },
            ),
            1,
        )
        validate_error(
            api.close_threat_case(
                ctx["case"]["id"],
                build_closure(
                    closure_summary="Attempting to close after the escort was lost."
                ),
                ctx["headers"]["threat_team_lead"],
            ),
            ApiErrorId.OPEN_ACTIONS_BLOCK_CLOSE,
            409,
        )
        assert_case_state(read_case(api, ctx), status="MONITORING")

    def test_separating_a_seated_member_recuses_the_seat_and_breaks_the_quorum(
        self, api: ApiClient
    ) -> None:
        """The legal seat loses its cast ballot, the round count falls to four and quorum breaks with no case call.

        PRD: "Fifth, every team seat held by the departing worker whose `status` is `ASSIGNED` becomes `RECUSED` with its ballot fields cleared, and each affected case's `quorum_met` and `ballot_count_current_round` are recomputed — a recusal can therefore break a quorum that was previously met."
        Design: Corner/state_machines/separating_a_seated_member_recuses_the_seat_and_clears_its_ballot
        """
        ctx = setup_deliberating_case(api)
        seat_id = ctx["seats"]["legal"]["id"]
        seat = get_success_data(
            api.get_team_assignment(seat_id, ctx["headers"]["threat_team_lead"])
        )
        assert seat["status"] == "ASSIGNED"
        assert_seat_ballot(seat, ballot_value="IMMINENT", ballot_round=1)
        assert_case_state(
            read_case(api, ctx),
            status="DELIBERATION",
            quorum_met=True,
            ballot_count_current_round=5,
        )

        separated = get_success_data(
            api.separate_employee(
                ctx["legal"]["id"],
                build_separation(
                    separation_reason="Legal representative transferred out of the region."
                ),
                ctx["headers"]["hr_partner"],
            )
        )

        assert separated["employment_status"] == "SEPARATED"
        recused = get_success_data(
            api.get_team_assignment(seat_id, ctx["headers"]["threat_team_lead"])
        )
        assert recused["status"] == "RECUSED"
        assert_seat_ballot_cleared(recused)
        assert_case_state(
            read_case(api, ctx),
            status="DELIBERATION",
            quorum_met=False,
            ballot_count_current_round=4,
        )
        assert_total_count(
            api.list_team_assignments(
                ctx["headers"]["threat_team_lead"],
                {"case_id": ctx["case"]["id"], "status": "ASSIGNED"},
            ),
            4,
        )


class TestDrillLapse:
    """The one drill transition with no endpoint of its own belongs to the sweep."""

    def test_the_sweep_marks_both_past_scheduled_drills_missed(self, api: ApiClient) -> None:
        """Advancing the clock past both scheduled times and sweeping lapses them without crediting anything.

        PRD: "Drills lapse: a `SCHEDULED` drill whose `scheduled_at` is strictly before the clock becomes `MISSED`."
        Design: Corner/state_machines/drill_sweep_marks_a_past_scheduled_drill_missed
        """
        ctx = setup_drilled_plan(api)
        assert ctx["drill_one"]["status"] == "SCHEDULED"
        assert ctx["drill_two"]["status"] == "SCHEDULED"

        assert move_clock(api, "2026-08-02T00:00:00Z") == "2026-08-02T00:00:00Z"
        counters = run_daily_sweep(api)

        assert_sweep_counters(counters, drills_missed_count=2, plans_rescored_count=1)
        first = get_success_data(
            api.get_drill(ctx["drill_one"]["id"], PROGRAM_ADMIN_HEADERS)
        )
        second = get_success_data(
            api.get_drill(ctx["drill_two"]["id"], PROGRAM_ADMIN_HEADERS)
        )
        assert first["status"] == "MISSED"
        assert second["status"] == "MISSED"
        assert first["executed_at"] is None
        assert first["participant_count"] is None
        assert first["participation_pct"] is None
        assert first["credited"] is False
        plan = read_plan(api, ctx)
        assert_plan_metrics(plan, drills_completed_12mo=0)
        assert_plan_state(plan, status="ACTIVE")
