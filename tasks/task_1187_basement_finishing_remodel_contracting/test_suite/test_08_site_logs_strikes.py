"""Daily site logs, strike escalation, suspension cascade, and resume tests."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_daily_site_log,
    create_inspection_payload,
    create_site_log_payload,
    create_started_phase,
    file_site_log,
    file_violation_log,
    get_success_data,
    make_contractor_headers,
    make_subcontractor_headers,
    set_logical_clock,
    setup_in_progress_project,
    setup_suspended_project,
    validate_error,
    validate_success,
)

INSPECTOR = TEST_USERS["inspector_headers"]


def _setup_cascade_scenario(api):
    """IN_PROGRESS project: ELECTRICAL phase started, ROUGH_IN inspection requested,
    clock at 2026-06-05, two violation logs already filed (06-01, 06-03)."""
    ctx = setup_in_progress_project(
        trade="ELECTRICAL", zone="REC_ROOM", address="8 H St", basement_sqft=950,
        base_contract_cents=7000000,
        phase_overrides={"start_date": "2026-06-01", "end_date": "2026-06-20"},
    )
    proj_id = ctx["project"]["id"]
    ctr_h = make_contractor_headers(ctx["contractor"]["id"])
    sub_id = ctx["subcontractor"]["id"]
    insp = get_success_data(
        api.create_inspection(
            proj_id,
            create_inspection_payload(type="ROUGH_IN", work_phase_id=ctx["phase"]["id"]),
            ctr_h,
        )
    )
    set_logical_clock("2026-06-05T00:00:00Z")
    file_site_log(proj_id, sub_id, "2026-06-01", containment_intact=False,
                  hepa_run_hours=6, noise_db_max=60, cleanup_completed=True)
    file_site_log(proj_id, sub_id, "2026-06-03", containment_intact=True,
                  hepa_run_hours=6, noise_db_max=60, cleanup_completed=False)
    ctx["inspection"] = insp
    return ctx


class TestStrikeSuspensionCascade:
    def test_third_violation_applies_strike_and_suspends_project(self, api):
        """PRD §3.7: "A log is flagged as a `violation` when containment was not
        intact, or cleanup was not completed, or peak noise exceeded 65 decibels."
        PRD §3.7: "When a new log raises the count to 3, the strike lands: that log's
        `strike_applied` flag becomes true (it is false otherwise), and the project
        moves from `IN_PROGRESS` to `SUSPENDED`."

        Design: Difficulty/transitive_cascade/strike_suspension_cascade
        """
        ctx = _setup_cascade_scenario(api)
        res = api.create_site_log(
            ctx["project"]["id"],
            create_site_log_payload(
                work_date="2026-06-05", containment_intact=True,
                hepa_run_hours=4, noise_db_max=70, cleanup_completed=True,
            ),
            make_subcontractor_headers(ctx["subcontractor"]["id"]),
        )
        log3 = validate_success(res, 201)
        assert log3["violation"] is True, "peak noise 70 exceeds 65"
        assert log3["strike_applied"] is True
        proj = get_success_data(
            api.get_project(
                ctx["project"]["id"],
                make_contractor_headers(ctx["contractor"]["id"]),
            )
        )
        assert proj["strike_count"] == 3
        assert proj["status"] == "SUSPENDED"

    def test_suspension_blocks_phase_and_cancels_requested_inspection(self, api):
        """PRD §3.7: "Suspension cascades immediately. Every work phase of the
        project in `IN_PROGRESS` or `READY` moves to `BLOCKED`, capturing its prior
        state in `pre_block_status` — a field that stays null on any phase that is
        not currently blocked; every outstanding `REQUESTED` inspection on the
        project moves to `CANCELLED`; and the project's `version` increments."

        Design: Difficulty/transitive_cascade/strike_suspension_cascade
        """
        ctx = _setup_cascade_scenario(api)
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        validate_success(
            api.create_site_log(
                ctx["project"]["id"],
                create_site_log_payload(
                    work_date="2026-06-05", containment_intact=True,
                    hepa_run_hours=4, noise_db_max=70, cleanup_completed=True,
                ),
                make_subcontractor_headers(ctx["subcontractor"]["id"]),
            ),
            201,
        )
        phase = get_success_data(api.get_work_phase(ctx["phase"]["id"], ctr_h))
        assert phase["status"] == "BLOCKED"
        assert phase["pre_block_status"] == "IN_PROGRESS"
        inspections = api.list_inspections(ctx["project"]["id"], ctr_h).json()["data"]
        by_id = {i["id"]: i for i in inspections}
        assert by_id[ctx["inspection"]["id"]]["status"] == "CANCELLED"


class TestStrikeThresholdBoundary:
    def _setup_paint_project(self, api):
        return setup_in_progress_project(
            trade="PAINT", zone="STUDIO", address="14 N St", basement_sqft=620,
            base_contract_cents=2600000,
            phase_overrides={"start_date": "2026-06-01", "end_date": "2026-06-14"},
            clock_iso="2026-06-05T00:00:00Z",
        )

    def test_two_in_window_violations_do_not_suspend(self, api):
        """PRD §3.7: "When a new log raises the count to 3, the strike lands: that
        log's `strike_applied` flag becomes true (it is false otherwise), and the
        project moves from `IN_PROGRESS` to `SUSPENDED`."

        Design: Difficulty/boundary_precision_check/strike_count_threshold_three
        """
        ctx = self._setup_paint_project(api)
        proj_id = ctx["project"]["id"]
        sub_id = ctx["subcontractor"]["id"]
        log1 = file_violation_log(proj_id, sub_id, "2026-06-03")
        log2 = file_violation_log(proj_id, sub_id, "2026-06-04")
        assert log1["strike_applied"] is False
        assert log2["strike_applied"] is False
        proj = get_success_data(
            api.get_project(proj_id, make_contractor_headers(ctx["contractor"]["id"]))
        )
        assert proj["strike_count"] == 2
        assert proj["status"] == "IN_PROGRESS"

    def test_third_in_window_violation_suspends(self, api):
        """PRD §3.7: "When a new log raises the count to 3, the strike lands: that
        log's `strike_applied` flag becomes true (it is false otherwise), and the
        project moves from `IN_PROGRESS` to `SUSPENDED`."

        Design: Difficulty/boundary_precision_check/strike_count_threshold_three
        """
        ctx = self._setup_paint_project(api)
        proj_id = ctx["project"]["id"]
        sub_id = ctx["subcontractor"]["id"]
        file_violation_log(proj_id, sub_id, "2026-06-03")
        file_violation_log(proj_id, sub_id, "2026-06-04")
        log3 = file_violation_log(proj_id, sub_id, "2026-06-05")
        assert log3["strike_applied"] is True
        proj = get_success_data(
            api.get_project(proj_id, make_contractor_headers(ctx["contractor"]["id"]))
        )
        assert proj["strike_count"] == 3
        assert proj["status"] == "SUSPENDED"


class TestSuspendedProjectGuards:
    def test_state_gate_beats_future_date_on_suspended_project(self, api):
        """PRD §2.6: "Every request is validated in a fixed priority order, and the
        first failing check produces the response — later checks are not consulted."
        PRD §2.7: "Daily site logs and inspection requests open only while the build
        is `IN_PROGRESS`."
        PRD §2.7: "A creation attempted in any other project state is rejected with
        `ERR_PROJECT_STATE_FORBIDS`."

        Design: Difficulty/priority_pair_validation_conflict/suspended_project_state_beats_future_date
        """
        ctx = setup_suspended_project(address="10 J St", basement_sqft=600,
                                      base_contract_cents=2500000)
        # Clock is 2026-06-05; the work_date 2026-06-06 is future-dated AND the
        # project is SUSPENDED — the project-state gate reports first.
        res = api.create_site_log(
            ctx["project"]["id"],
            create_site_log_payload(
                work_date="2026-06-06", containment_intact=True,
                hepa_run_hours=2, noise_db_max=50, cleanup_completed=True,
            ),
            make_subcontractor_headers(ctx["subcontractor"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PROJECT_STATE_FORBIDS)

    def test_rejected_site_log_persists_nothing(self, api):
        """PRD §2.6: "Every request is validated in a fixed priority order, and the
        first failing check produces the response — later checks are not consulted."
        PRD §3.7: "every role can list a project's logs"

        Design: Difficulty/priority_pair_validation_conflict/suspended_project_state_beats_future_date
        """
        ctx = setup_suspended_project(address="10 J St", basement_sqft=600,
                                      base_contract_cents=2500000)
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        res = api.create_site_log(
            ctx["project"]["id"],
            create_site_log_payload(
                work_date="2026-06-06", containment_intact=True,
                hepa_run_hours=2, noise_db_max=50, cleanup_completed=True,
            ),
            make_subcontractor_headers(ctx["subcontractor"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PROJECT_STATE_FORBIDS)
        logs = api.list_site_logs(ctx["project"]["id"], ctr_h).json()["data"]
        assert len(logs) == 3, "the rejected filing must persist no log"


class TestSiteLogShapeAndDates:
    def test_site_log_immutable_no_version_field(self, api):
        """PRD §2.4: "The DailySiteLog is the sole exception to this convention. As an
        immutable daily record, it carries only `id` and `created_at`; both
        `updated_at` and `version` are absent."
        PRD §3.7: "A log is flagged as a `violation` when containment was not intact,
        or cleanup was not completed, or peak noise exceeded 65 decibels."

        Design: Corner/entities/site_log_immutable_no_version_field
        """
        ctx = setup_in_progress_project(
            trade="PAINT", zone="REC", address="5 Corner Way",
            clock_iso="2026-06-05T00:00:00Z",
        )
        res = api.create_site_log(
            ctx["project"]["id"],
            create_site_log_payload(
                work_date="2026-06-05", containment_intact=True,
                hepa_run_hours=5, noise_db_max=55, cleanup_completed=True,
            ),
            make_subcontractor_headers(ctx["subcontractor"]["id"]),
        )
        log = validate_success(res, 201)
        assert_daily_site_log(log)
        assert log["violation"] is False
        assert log["strike_applied"] is False
        assert log["subcontractor_id"] == ctx["subcontractor"]["id"]

    def test_future_work_date_rejected(self, api):
        """PRD §3.7: "The payload records the `work_date` — which must not be after
        the current logical clock date, or filing is rejected with
        `ERR_FUTURE_WORK_DATE`"

        Design: Corner/validations/future_work_date_rejected
        """
        ctx = setup_in_progress_project(
            trade="PAINT", zone="REC", address="V4 St",
            clock_iso="2026-06-05T00:00:00Z",
        )
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        res = api.create_site_log(
            ctx["project"]["id"],
            create_site_log_payload(
                work_date="2026-06-06", containment_intact=True,
                hepa_run_hours=4, noise_db_max=55, cleanup_completed=True,
            ),
            make_subcontractor_headers(ctx["subcontractor"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FUTURE_WORK_DATE)
        logs = api.list_site_logs(ctx["project"]["id"], ctr_h).json()["data"]
        assert logs == [], "the rejected filing must persist no log"


class TestResumeAndStrikeWindow:
    def test_resume_restores_blocked_phases_and_resets_strikes(self, api):
        """PRD §3.7: "Resuming sets `last_resumed_at` to the current logical clock and
        re-anchors the strike window, so `strike_count` recomputes to zero — logs
        created before the resume are excluded from the count."
        PRD §3.7: "Every `BLOCKED` phase restores its captured `pre_block_status`,
        returning to `READY` or `IN_PROGRESS` as recorded, and the field is cleared."

        Design: Corner/state_machines/resume_restores_blocked_phases_and_resets_strikes
        """
        ctx = setup_suspended_project(address="13 Corner Way")
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        resumed = validate_success(
            api.resume_project(
                ctx["project"]["id"],
                {"remediation_note": "reinstalled containment, crew retrained"},
                ctr_h,
            ),
            200,
        )
        assert resumed["status"] == "IN_PROGRESS"
        assert resumed["strike_count"] == 0
        assert str(resumed["last_resumed_at"]).startswith("2026-06-05"), (
            "last_resumed_at is set from the current logical clock (2026-06-05)"
        )
        phase = get_success_data(api.get_work_phase(ctx["phase"]["id"], ctr_h))
        assert phase["status"] == "IN_PROGRESS"
        assert phase["pre_block_status"] is None

    def test_strike_window_excludes_pre_resume_logs(self, api):
        """PRD §3.7: "Resuming sets `last_resumed_at` to the current logical clock and
        re-anchors the strike window, so `strike_count` recomputes to zero — logs
        created before the resume are excluded from the count."

        Design: Corner/calculations/strike_window_excludes_pre_resume_logs
        """
        ctx = setup_suspended_project(address="18 Corner Way")
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        sub_id = ctx["subcontractor"]["id"]
        validate_success(
            api.resume_project(
                ctx["project"]["id"], {"remediation_note": "fixed"}, ctr_h
            ),
            200,
        )
        log = file_site_log(
            ctx["project"]["id"], sub_id, "2026-06-05",
            containment_intact=True, hepa_run_hours=3, noise_db_max=70,
            cleanup_completed=True,
        )
        assert log["violation"] is True
        assert log["strike_applied"] is False
        proj = get_success_data(api.get_project(ctx["project"]["id"], ctr_h))
        assert proj["strike_count"] == 1, (
            "only the post-resume violation counts; the three pre-resume logs are "
            "excluded from the re-anchored window"
        )
        assert proj["status"] == "IN_PROGRESS"
