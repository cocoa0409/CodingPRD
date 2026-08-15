"""Regulatory surveys and environmental permits: branching survey outcomes,
the completion gate, surveyor-calendar conflicts, hot-work grant exclusivity,
and clock-driven expiry."""
from test_helpers import (
    EO,
    PM,
    SV1,
    SV2,
    ApiErrorId,
    apply_permit,
    assert_timestamp_instant,
    complete_item,
    create_draft_project,
    create_permit_payload,
    create_survey_payload,
    get_project,
    get_success_data,
    grant_permit,
    schedule_survey,
    set_clock,
    setup_in_dock_project,
    start_item,
    validate_error,
    validate_success,
)

SURVEY_GATED_ITEM = {
    "description": "Propeller polish", "trade_code": "MACHINERY",
    "duration_days": 3, "quantity": 1, "unit_price_cents": 800000,
}


def _setup_gated_project_with_completed_work(api, survey_type):
    """IN_DOCK project whose only work item is COMPLETE, with one survey of
    `survey_type` SCHEDULED — the survey gate alone holds the project."""
    ctx = setup_in_dock_project(
        item_specs=[SURVEY_GATED_ITEM], required_survey_types=[survey_type]
    )
    start_item(ctx["items"][0]["id"])
    complete_item(ctx["items"][0]["id"])
    survey = schedule_survey(ctx["project"]["id"], survey_type=survey_type)
    return ctx, survey


class TestSurveyFailThenResurvey:
    def test_failed_survey_holds_project_and_is_terminal(self, api):
        """PRD §3.6: "A recorded `FAILED` leaves the project in `IN_DOCK`: the
        failure is superseded by booking a fresh survey of the same
        `survey_type`, because the completion gate consults only the latest
        survey of each required type."
        PRD §3.6: "Both outcomes are terminal for the survey."

        Design: Difficulty/non_linear_state_machine/survey_fail_then_resurvey_branch
        """
        ctx, survey = _setup_gated_project_with_completed_work(api, "USCG_INSPECTION")

        failed = validate_success(api.record_survey_result(
            survey["id"], {"result": "FAILED", "deficiency_count": 2}, SV1
        ))
        assert failed["status"] == "FAILED"

        project = get_project(ctx["project"]["id"])
        assert project["status"] == "IN_DOCK", (
            "The FAILED branch does not release the project"
        )

        resp = api.record_survey_result(survey["id"], {"result": "PASSED"}, SV1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_replacement_survey_pass_releases_project(self, api):
        """PRD §3.6: "A recorded `FAILED` leaves the project in `IN_DOCK`: the
        failure is superseded by booking a fresh survey of the same
        `survey_type`, because the completion gate consults only the latest
        survey of each required type."
        PRD §3.7: "The gate is re-evaluated whenever a work item completes and
        whenever a survey is recorded `PASSED`, and it opens when two
        conditions hold together: every work item of the project is in
        `COMPLETE` or `CANCELLED`, and for every entry of
        `required_survey_types` the project's latest survey of that type —
        latest by creation timestamp — is `PASSED`."

        Design: Difficulty/non_linear_state_machine/survey_fail_then_resurvey_branch
        """
        ctx, survey = _setup_gated_project_with_completed_work(api, "USCG_INSPECTION")
        get_success_data(api.record_survey_result(
            survey["id"], {"result": "FAILED", "deficiency_count": 2}, SV1
        ))

        replacement = schedule_survey(
            ctx["project"]["id"], survey_type="USCG_INSPECTION",
            start="2026-08-03T09:00:00Z", end="2026-08-03T10:00:00Z",
        )
        passed = validate_success(api.record_survey_result(
            replacement["id"], {"result": "PASSED"}, SV1
        ))
        assert passed["status"] == "PASSED"

        project = get_project(ctx["project"]["id"])
        assert project["status"] == "WORK_COMPLETE", (
            "The newer PASSED survey of the required type releases the gate"
        )


class TestCompletionGateAwaitsPassedSurvey:
    def test_completion_withheld_while_latest_survey_failed(self, api):
        """PRD §3.7: "The gate is re-evaluated whenever a work item completes
        and whenever a survey is recorded `PASSED`, and it opens when two
        conditions hold together: every work item of the project is in
        `COMPLETE` or `CANCELLED`, and for every entry of
        `required_survey_types` the project's latest survey of that type —
        latest by creation timestamp — is `PASSED`."

        Design: Difficulty/cross_entity_state_dependency/project_completion_gate_awaits_passed_survey
        """
        ctx, survey = _setup_gated_project_with_completed_work(api, "USCG_INSPECTION")
        get_success_data(api.record_survey_result(
            survey["id"], {"result": "FAILED", "deficiency_count": 2}, SV1
        ))
        project = get_project(ctx["project"]["id"])
        assert project["status"] == "IN_DOCK", (
            "All work COMPLETE but the latest USCG_INSPECTION survey is FAILED — "
            "completion is a function of survey state"
        )

    def test_completion_released_by_newer_passed_survey(self, api):
        """PRD §3.7: "for every entry of `required_survey_types` the project's
        latest survey of that type — latest by creation timestamp — is
        `PASSED`"

        Design: Difficulty/cross_entity_state_dependency/project_completion_gate_awaits_passed_survey
        """
        ctx, survey = _setup_gated_project_with_completed_work(api, "USCG_INSPECTION")
        get_success_data(api.record_survey_result(
            survey["id"], {"result": "FAILED", "deficiency_count": 2}, SV1
        ))
        replacement = schedule_survey(
            ctx["project"]["id"], survey_type="USCG_INSPECTION",
            start="2026-08-03T09:00:00Z", end="2026-08-03T10:00:00Z",
        )
        get_success_data(api.record_survey_result(
            replacement["id"], {"result": "PASSED"}, SV1
        ))
        project = get_project(ctx["project"]["id"])
        assert project["status"] == "WORK_COMPLETE", (
            "The newer PASSED survey releases the completion gate"
        )


class TestFinalSurveyPassUndocksProject:
    def test_gate_withheld_while_required_survey_only_scheduled(self, api):
        """PRD §3.7: "The transition from `IN_DOCK` to `WORK_COMPLETE` is
        automatic — no operator invokes it. The gate is re-evaluated whenever a
        work item completes and whenever a survey is recorded `PASSED`, and it
        opens when two conditions hold together: every work item of the project
        is in `COMPLETE` or `CANCELLED`, and for every entry of
        `required_survey_types` the project's latest survey of that type —
        latest by creation timestamp — is `PASSED`."

        Design: Difficulty/transitive_cascade/final_survey_pass_undocks_project
        """
        ctx, survey = _setup_gated_project_with_completed_work(api, "CLASS_RENEWAL")
        project = get_project(ctx["project"]["id"])
        assert project["status"] == "IN_DOCK", (
            "A merely SCHEDULED survey is not PASSED — completion is withheld"
        )

    def test_survey_pass_releases_active_reservation(self, api):
        """PRD §3.7: "When the gate opens, the project's `ACTIVE` dock
        reservation is released in the same stroke, moving to `RELEASED` with
        `released_at_utc` set to the current logical time and freeing the dock
        window, and the project's `version` increments by one."

        Design: Difficulty/transitive_cascade/final_survey_pass_undocks_project
        """
        ctx, survey = _setup_gated_project_with_completed_work(api, "CLASS_RENEWAL")
        get_success_data(api.record_survey_result(
            survey["id"], {"result": "PASSED"}, SV1
        ))
        project = get_project(ctx["project"]["id"])
        assert project["status"] == "WORK_COMPLETE"

        reservation = get_success_data(
            api.get_dock_reservation(ctx["reservation"]["id"], PM)
        )
        assert reservation["status"] == "RELEASED", (
            "The project transition — not the survey call directly — releases "
            "the reservation"
        )
        assert_timestamp_instant(
            reservation["released_at_utc"], "2026-08-01T00:00:00"
        )


class TestSurveyorCalendarConflicts:
    def test_touching_interval_same_surveyor_conflicts(self, api):
        """PRD §3.6: "bookings are checked against that surveyor's own calendar
        under closed-interval semantics: any overlap with another of the same
        surveyor's `SCHEDULED` surveys — including a new survey whose start
        coincides exactly with another's end — is rejected with
        `ERR_SURVEYOR_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/surveyor_back_to_back_closed_interval_conflict
        """
        project = create_draft_project()
        schedule_survey(
            project["id"], survey_type="CLASS_INTERMEDIATE",
            start="2026-08-04T09:00:00Z", end="2026-08-04T12:00:00Z",
        )
        resp = api.create_survey(
            create_survey_payload(
                project["id"], survey_type="LOAD_LINE",
                scheduled_start_utc="2026-08-04T12:00:00Z",
                scheduled_end_utc="2026-08-04T15:00:00Z",
            ),
            SV1,
        )
        validate_error(resp, ApiErrorId.ERR_SURVEYOR_SCHEDULE_CONFLICT)

    def test_identical_window_under_other_surveyor_allowed(self, api):
        """PRD §2.7: "Surveys, by contrast, are booked under closed-interval
        semantics: touching endpoints count as overlap."
        PRD §3.6: "bookings are checked against that surveyor's own calendar"

        Design: Difficulty/resource_temporal_overlap/surveyor_back_to_back_closed_interval_conflict
        """
        project = create_draft_project()
        schedule_survey(
            project["id"], survey_type="CLASS_INTERMEDIATE",
            start="2026-08-04T09:00:00Z", end="2026-08-04T12:00:00Z",
        )
        other = validate_success(api.create_survey(
            create_survey_payload(
                project["id"], survey_type="LOAD_LINE",
                scheduled_start_utc="2026-08-04T09:00:00Z",
                scheduled_end_utc="2026-08-04T12:00:00Z",
            ),
            SV2,
        ), 201)
        assert other["status"] == "SCHEDULED", (
            "The conflict check keys on the surveyor's own calendar — an "
            "identical window under a different surveyor conflicts with nothing"
        )


class TestSurveyResultDiscipline:
    def test_survey_result_deficiency_discipline(self, api):
        """PRD §3.6: "A `result` of `PASSED` requires `deficiency_count` to be
        omitted or zero; a `result` of `FAILED` requires a `deficiency_count`
        of at least one; any other combination is rejected with
        `ERR_SURVEY_RESULT_INVALID`."

        Design: Corner/errors/survey_result_deficiency_discipline
        """
        project = create_draft_project()
        survey1 = schedule_survey(
            project["id"], survey_type="CLASS_INTERMEDIATE",
            start="2026-08-04T09:00:00Z", end="2026-08-04T10:00:00Z",
        )
        survey2 = schedule_survey(
            project["id"], survey_type="LOAD_LINE",
            start="2026-08-05T09:00:00Z", end="2026-08-05T10:00:00Z",
        )

        resp1 = api.record_survey_result(survey1["id"], {"result": "FAILED"}, SV1)
        validate_error(resp1, ApiErrorId.ERR_SURVEY_RESULT_INVALID)

        resp2 = api.record_survey_result(
            survey2["id"], {"result": "PASSED", "deficiency_count": 1}, SV1
        )
        validate_error(resp2, ApiErrorId.ERR_SURVEY_RESULT_INVALID)

        untouched = get_success_data(api.get_survey(survey1["id"], SV1))
        assert untouched["status"] == "SCHEDULED", (
            "Rejected recordings leave the survey state untouched"
        )

    def test_survey_record_by_other_surveyor_returns_ownership_mismatch(self, api):
        """PRD §3.6: "Recording the outcome belongs to the surveyor who booked
        it: the recorder's `X-User-ID` is compared against `surveyor_user_id`,
        and a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH`."

        Design: Corner/errors/survey_record_by_other_surveyor_returns_ownership_mismatch
        """
        project = create_draft_project()
        survey = schedule_survey(
            project["id"], survey_type="CLASS_INTERMEDIATE",
            start="2026-08-04T09:00:00Z", end="2026-08-04T10:00:00Z",
        )
        resp = api.record_survey_result(survey["id"], {"result": "PASSED"}, SV2)
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)


class TestPermits:
    def test_hot_work_permit_conflict_on_touching_days(self, api):
        """PRD §3.6: "For `HOT_WORK` the grant is exclusive per dock: if any
        other `GRANTED` hot-work permit exists for a project sharing the same
        dock whose closed day-interval overlaps the applicant's — touching days
        count as overlap — the grant is rejected with
        `ERR_HOT_WORK_PERMIT_CONFLICT`."

        Design: Corner/errors/hot_work_permit_conflict_on_touching_days
        """
        project1 = create_draft_project()
        project2 = create_draft_project(
            dock_id=project1["dock_id"], vessel_id=project1["vessel_id"]
        )
        hw1 = apply_permit(
            project1["id"], permit_type="HOT_WORK",
            valid_from="2026-08-01T00:00:00Z", valid_to="2026-08-10T23:59:59Z",
        )
        grant_permit(hw1["id"])

        hw2 = apply_permit(
            project2["id"], permit_type="HOT_WORK",
            valid_from="2026-08-10T00:00:00Z", valid_to="2026-08-15T23:59:59Z",
        )
        resp = api.grant_permit(hw2["id"], EO)
        validate_error(resp, ApiErrorId.ERR_HOT_WORK_PERMIT_CONFLICT)

        hw3 = apply_permit(
            project2["id"], permit_type="HOT_WORK",
            valid_from="2026-08-11T00:00:00Z", valid_to="2026-08-15T23:59:59Z",
        )
        granted = validate_success(api.grant_permit(hw3["id"], EO))
        assert granted["status"] == "GRANTED", (
            "08-11..08-15 shares no day with 08-01..08-10 — disjoint windows grant"
        )

    def test_permit_window_reversed_returns_permit_window_invalid(self, api):
        """PRD §3.6: "the window is a closed, day-granular interval, and
        `valid_to` must be strictly after `valid_from` or the application is
        rejected with `ERR_PERMIT_WINDOW_INVALID`."

        Design: Corner/validations/permit_window_reversed_returns_permit_window_invalid
        """
        project = create_draft_project()
        resp = api.create_permit(
            create_permit_payload(
                project["id"], permit_type="PAINT_SPRAY",
                valid_from="2026-08-10T00:00:00Z", valid_to="2026-08-05T00:00:00Z",
            ),
            EO,
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_WINDOW_INVALID)

    def test_permit_expiry_sweep_on_clock_set(self, api):
        """PRD §2.5: "Setting the clock is not inert: each advance runs two
        sweeps. First, any permit still in `APPLIED`, `GRANTED`, or `SUSPENDED`
        whose `valid_to` lies strictly before the new logical time transitions
        to `EXPIRED`."

        Design: Corner/state_machines/permit_expiry_sweep_on_clock_set
        """
        project = create_draft_project()
        permit = apply_permit(
            project["id"], permit_type="HOT_WORK",
            valid_from="2026-08-01T00:00:00Z", valid_to="2026-08-10T23:59:59Z",
        )
        grant_permit(permit["id"])

        set_clock("2026-08-11T00:00:00Z")
        swept = get_success_data(api.get_permit(permit["id"], EO))
        assert swept["status"] == "EXPIRED", (
            "2026-08-11T00:00:00Z lies strictly past valid_to "
            "2026-08-10T23:59:59Z"
        )
