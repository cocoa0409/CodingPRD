"""Accepted-impact schedule cascade and RFI close gating (PRD §3.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    accept_assessment,
    activate_spec_section,
    add_reviewer,
    add_spec_section,
    add_subcontractor,
    answer_rfi,
    assert_contingency_conserved,
    assessment_for_rfi,
    create_active_project,
    create_activity,
    create_rfi,
    escalation_events,
    get_activity,
    get_project,
    get_submittal,
    lli_of_submittal,
    price_assessment,
    route_rfi,
    set_clock,
    setup_approved_submittal,
    setup_estimated_assessment,
    submittals_of_section,
    waive_assessment,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["project_manager_headers"]
PE = TEST_USERS["project_engineer_headers"]


class TestAcceptScheduleCascadeDepth4:
    def _cascade_world(self, api):
        """Long-lead world scanned six days late, with a PLANNED activity and a priced
        cost+schedule (7 days) impact assessment ready to accept."""
        project = create_active_project("Cascade", initial_contingency_cents=2_000_000)
        subcontractor = add_subcontractor(
            project["id"], company_name="SteelFab", trade="structural steel"
        )
        reviewer = add_reviewer(project["id"], display_name="Arch One", discipline="ARCH")
        section = add_spec_section(
            project["id"],
            "051200",
            lead_time_days=35,
            review_days=10,
            default_need_date="2026-08-15",
            responsible_subcontractor_id=subcontractor["id"],
            required_submittal_kinds=["SHOP_DRAWINGS"],
        )
        activate_spec_section(section["id"])
        submittal = submittals_of_section(project["id"], "051200")[0]
        lli = lli_of_submittal(submittal["id"])

        set_clock("2026-08-21T00:00:00Z")
        validate_success(api.run_daily_scan(project["id"], PM), 200)
        lli_late = validate_success(api.get_long_lead_item(lli["id"], PE), 200)

        activity = create_activity(
            project["id"],
            submittal["id"],
            subcontractor["id"],
            "2026-09-01",
            "2026-09-10",
        )

        rfi = create_rfi(
            project["id"],
            subject="Embed plates",
            question_text="Relocation?",
            submittal_id=submittal["id"],
        )
        route_rfi(rfi["id"], reviewer["id"])
        answer_rfi(
            rfi["id"],
            reviewer["id"],
            answer_text="Shift embeds",
            cost_impact_flag=True,
            schedule_impact_flag=True,
            estimated_cost_cents=100_000,
            estimated_schedule_days=7,
        )
        assessment = assessment_for_rfi(project["id"], rfi["id"])
        price_assessment(assessment["id"], 100_000)
        return {
            "project": project,
            "subcontractor": subcontractor,
            "reviewer": reviewer,
            "submittal": submittal,
            "lli": lli,
            "lli_level_pre": lli_late["escalation_level"],
            "activity": activity,
            "assessment": assessment,
        }

    def test_accept_cascade_shifts_activity_submittal_dates_and_ledger(self, api):
        """PRD §3.6: "Acceptance converts the reservation to spend —
        `contingency_reserved_cents` falls by `final_delta_cents` while
        `contingency_spent_cents` rises by the same amount, leaving the available balance
        unchanged"
        PRD §3.6: "Every `PLANNED` InstallationActivity whose `submittal_id` matches the
        RFI's linked submittal shifts later by d calendar days — both `start_date` and
        `end_date` move, and each activity's `shift_applied_days` accumulates d. The
        linked submittal's `required_on_site_date` shifts later by the same d calendar
        days, its `required_approval_date` and `required_submission_date` recompute
        through the pinned backward pass, and its `version` bumps."
        d = 7: the activity moves [2026-09-01, 2026-09-10) -> [2026-09-08, 2026-09-17);
        the submittal's on-site date moves 2026-08-15 -> 2026-08-22 with approval
        2026-07-06 and submission 2026-06-22 recomputed over business days.

        Design: Difficulty/transitive_cascade/accept_impact_schedule_cascade_depth4
        """
        world = self._cascade_world(api)
        accepted = accept_assessment(world["assessment"]["id"])
        assert accepted["status"] == "ACCEPTED"

        ledger = get_project(world["project"]["id"])
        assert ledger["contingency_spent_cents"] == 117_810
        assert ledger["contingency_reserved_cents"] == 0
        assert ledger["contingency_available_cents"] == 1_882_190
        assert_contingency_conserved(ledger)

        activity = get_activity(world["activity"]["id"])
        assert activity["start_date"] == "2026-09-08"
        assert activity["end_date"] == "2026-09-17"
        assert activity["shift_applied_days"] == 7

        submittal = get_submittal(world["submittal"]["id"])
        assert submittal["required_on_site_date"] == "2026-08-22"
        assert submittal["required_approval_date"] == "2026-07-06"
        assert submittal["required_submission_date"] == "2026-06-22"

    def test_accept_cascade_recomputes_lli_and_appends_cleared_event(self, api):
        """PRD §3.6: "The linked LongLeadItem then recomputes `days_late`,
        `escalation_level`, and `priority_score` against the new date with its own
        version bump, appending an `LLI_ESCALATION_RAISED` or `LLI_ESCALATION_CLEARED`
        event when its tier changes"
        The item stood at escalation level 1 (six days late at 2026-08-21); the +7 day
        shift moves the required date to 2026-08-22, beyond the clock, so lateness
        collapses to zero and the tier drop appends LLI_ESCALATION_CLEARED.

        Design: Difficulty/transitive_cascade/accept_impact_schedule_cascade_depth4
        """
        world = self._cascade_world(api)
        assert world["lli_level_pre"] == 1, "six days late at the 2026-08-21 scan"

        accept_assessment(world["assessment"]["id"])

        lli = validate_success(
            api.get_long_lead_item(world["lli"]["id"], PE), 200
        )
        assert lli["days_late"] == 0
        assert lli["escalation_level"] == 0

        cleared = escalation_events(
            event_type="LLI_ESCALATION_CLEARED", source_id=world["lli"]["id"]
        )
        assert len(cleared) == 1, "the tier change 1 -> 0 fires exactly one event"


class TestRfiCloseGate:
    def test_close_blocked_while_assessment_estimated(self, api):
        """PRD §3.5: "Closing an RFI, also by a `ProjectEngineer`, requires `ANSWERED`
        (otherwise `ERR_RFI_INVALID_STATE`) and is refused with
        `ERR_ASSESSMENT_OPEN_ON_CLOSE` while any of its assessments remains in
        `ESTIMATED`, `PRICED`, or `DISPUTED`."

        Design: Difficulty/cross_entity_state_dependency/rfi_close_requires_impact_assessment_terminal
        """
        ctx = setup_estimated_assessment()
        assert ctx["assessment"]["status"] == "ESTIMATED"
        resp = api.close_rfi(ctx["rfi"]["id"], PE)
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_OPEN_ON_CLOSE, 409)

    def test_close_succeeds_after_assessment_waived(self, api):
        """PRD §3.5: "Closing an RFI, also by a `ProjectEngineer`, requires `ANSWERED`
        (otherwise `ERR_RFI_INVALID_STATE`) and is refused with
        `ERR_ASSESSMENT_OPEN_ON_CLOSE` while any of its assessments remains in
        `ESTIMATED`, `PRICED`, or `DISPUTED`."
        After the assessment is priced and then waived (a terminal state), the same
        close succeeds.

        Design: Difficulty/cross_entity_state_dependency/rfi_close_requires_impact_assessment_terminal
        """
        ctx = setup_estimated_assessment()
        price_assessment(ctx["assessment"]["id"], 100_000)
        waive_assessment(ctx["assessment"]["id"])

        closed = validate_success(api.close_rfi(ctx["rfi"]["id"], PE), 200)
        assert closed["status"] == "CLOSED"


class TestConditionalCascade:
    def test_accept_with_zero_schedule_days_applies_no_shift(self, api):
        """PRD §3.6: "Acceptance additionally fires the schedule cascade whenever the
        source RFI declared `schedule_impact_flag` with `estimated_schedule_days` d
        greater than zero and the RFI references a submittal."
        With d == 0 the cascade is not conditional-met: the cost delta is accepted while
        the activity window and the submittal's dates stay untouched.

        Design: Corner/cross_cutting_layers/accept_with_zero_schedule_days_applies_no_shift
        """
        world = setup_approved_submittal(
            need_date="2026-10-30",
            lead_time_days=5,
            review_days=5,
            section_number="033000",
            project_overrides={"initial_contingency_cents": 2_000_000},
        )
        project = world["project"]
        submittal = world["submittal"]
        activity = create_activity(
            project["id"],
            submittal["id"],
            world["subcontractor"]["id"],
            "2026-11-02",
            "2026-11-10",
        )
        rfi = create_rfi(project["id"], subject="S", submittal_id=submittal["id"])
        route_rfi(rfi["id"], world["reviewer"]["id"])
        answer_rfi(
            rfi["id"],
            world["reviewer"]["id"],
            answer_text="minor",
            cost_impact_flag=True,
            schedule_impact_flag=True,
            estimated_cost_cents=100_000,
            estimated_schedule_days=0,
        )
        assessment = assessment_for_rfi(project["id"], rfi["id"])
        price_assessment(assessment["id"], 100_000)

        accepted = accept_assessment(assessment["id"])
        assert accepted["status"] == "ACCEPTED"

        activity_after = get_activity(activity["id"])
        assert activity_after["start_date"] == "2026-11-02"
        assert activity_after["shift_applied_days"] == 0, "no shift when d == 0"
        assert get_submittal(submittal["id"])["required_on_site_date"] == "2026-10-30"
