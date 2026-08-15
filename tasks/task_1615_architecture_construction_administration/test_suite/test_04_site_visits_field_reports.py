"""Site visits, field reports, issuance window, SoD, and nonconformance lifecycle."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_active_project,
    create_performed_visit,
    create_report_issued_visit,
    issue_field_report,
    set_clock,
    make_firm_admin_headers,
    make_architect_headers,
    USER_ARCH_2,
    USER_ARCH_3,
    USER_ARCH_LEAD,
)


def _active_single_line_project():
    return create_active_project(
        sov_lines=[{"line_code": "A", "description": "Concrete",
                    "scheduled_value_cents": 10000000}],
    )


class TestVisitDateConflict:
    def test_same_calendar_day_conflicts_adjacent_day_allowed(self, api):
        """PRD 3.3: "A project may host at most one non-cancelled visit per
        calendar date: if another visit on the same project already holds that
        `visit_date` in `SCHEDULED`, `PERFORMED`, or `REPORT_ISSUED`, the new
        schedule is rejected with `ERR_VISIT_DATE_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/site_visit_same_calendar_day_conflict
        """
        project = _active_single_line_project()
        first = validate_success(api.create_site_visit(
            {"project_id": project["id"], "visit_date": "2026-08-15",
             "purpose": "PROGRESS_OBSERVATION", "performed_by_user_id": USER_ARCH_2},
            make_architect_headers(),
        ), 201)
        conflict = api.create_site_visit(
            {"project_id": project["id"], "visit_date": "2026-08-15",
             "purpose": "PROGRESS_OBSERVATION", "performed_by_user_id": USER_ARCH_LEAD},
            make_architect_headers(),
        )
        validate_error(conflict, ApiErrorId.ERR_VISIT_DATE_CONFLICT, 409)
        adjacent = api.create_site_visit(
            {"project_id": project["id"], "visit_date": "2026-08-16",
             "purpose": "PROGRESS_OBSERVATION", "performed_by_user_id": USER_ARCH_LEAD},
            make_architect_headers(),
        )
        validate_success(adjacent, 201)

    def test_cancelling_releases_visit_date(self, api):
        """PRD 3.3: "Cancelling a `SCHEDULED` visit moves it to `CANCELLED` and
        releases its date for reuse."

        Design: Difficulty/resource_temporal_overlap/site_visit_same_calendar_day_conflict
        """
        project = _active_single_line_project()
        first = validate_success(api.create_site_visit(
            {"project_id": project["id"], "visit_date": "2026-08-15",
             "purpose": "PROGRESS_OBSERVATION", "performed_by_user_id": USER_ARCH_2},
            make_architect_headers(),
        ), 201)
        cancelled = validate_success(
            api.cancel_site_visit(first["id"], make_architect_headers()), 200)
        assert cancelled["status"] == "CANCELLED"
        rebooked = api.create_site_visit(
            {"project_id": project["id"], "visit_date": "2026-08-15",
             "purpose": "PAYMENT_VERIFICATION", "performed_by_user_id": USER_ARCH_2},
            make_architect_headers(),
        )
        validate_success(rebooked, 201)


class TestPerformCancelledVisit:
    def test_perform_cancelled_visit_returns_invalid_state(self, api):
        """PRD 3.3: "Performing or cancelling a visit that is not `SCHEDULED`
        fails with `ERR_SITE_VISIT_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/perform_cancelled_visit_returns_invalid_state
        """
        project = _active_single_line_project()
        visit = validate_success(api.create_site_visit(
            {"project_id": project["id"], "visit_date": "2026-08-15",
             "purpose": "PROGRESS_OBSERVATION", "performed_by_user_id": USER_ARCH_2},
            make_architect_headers(),
        ), 201)
        api.cancel_site_visit(visit["id"], make_architect_headers())
        resp = api.perform_site_visit(visit["id"], make_architect_headers())
        validate_error(resp, ApiErrorId.ERR_SITE_VISIT_INVALID_STATE, 409)
        current = get_success_data(api.get_site_visit(visit["id"], make_architect_headers()))
        assert current["status"] == "CANCELLED"
        assert current["performed_at"] is None


class TestSecondFieldReportSameVisit:
    def test_second_field_report_same_visit_returns_visit_state_error(self, api):
        """PRD 3.3: "the visit must be in `PERFORMED` (any other state, including
        a visit that already has its report, yields `ERR_SITE_VISIT_INVALID_STATE`)"
        and "the visit advances from `PERFORMED` to `REPORT_ISSUED` — which is
        itself what enforces the one-report rule, since a second issuance attempt
        finds the visit no longer `PERFORMED`."

        Design: Corner/validations/second_field_report_same_visit_returns_visit_state_error
        """
        project = _active_single_line_project()
        set_clock("2026-08-20T09:00:00Z")
        visit, _report = create_report_issued_visit(
            project["id"], visit_date="2026-08-20", purpose="PROGRESS_OBSERVATION",
        )
        assert visit["status"] == "REPORT_ISSUED"
        resp = api.create_field_report(
            {"site_visit_id": visit["id"], "issued_by_user_id": USER_ARCH_3,
             "conformance_summary": "CONFORMING", "nonconforming_work_flag": False},
            make_architect_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_SITE_VISIT_INVALID_STATE, 409)
        reports = get_success_data(api.list_field_reports(
            make_architect_headers(), params={"site_visit_id": visit["id"]}))
        assert len(reports) == 1


class TestFieldReportWindow:
    def test_field_report_after_window_expires_returns_409(self, api):
        """PRD 3.3: "the issuance date read from the clock must be no later than
        the visit's performed date plus the project's `field_report_window_days`
        calendar days (otherwise `ERR_FIELD_REPORT_WINDOW_EXPIRED`, HTTP 409)."

        Design: Corner/validations/field_report_after_window_expires_returns_409
        """
        project = _active_single_line_project()
        set_clock("2026-08-20T09:00:00Z")
        visit = create_performed_visit(
            project["id"], visit_date="2026-08-20", purpose="PROGRESS_OBSERVATION",
        )
        set_clock("2026-08-24T09:00:00Z")
        resp = api.create_field_report(
            {"site_visit_id": visit["id"], "issued_by_user_id": USER_ARCH_LEAD,
             "conformance_summary": "CONFORMING", "nonconforming_work_flag": False},
            make_architect_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_FIELD_REPORT_WINDOW_EXPIRED, 409)
        current = get_success_data(api.get_site_visit(visit["id"], make_architect_headers()))
        assert current["status"] == "PERFORMED"


class TestSodReportIssuerIsPerformer:
    def test_sod_report_issuer_equals_performer_rejected(self, api):
        """PRD 2.10: "on issuance, `issued_by_user_id` must differ from the
        visit's `performed_by_user_id`, or the issuance fails with
        `ERR_SOD_REPORT_ISSUER_IS_PERFORMER` (HTTP 422)."

        Design: Corner/validations/sod_report_issuer_equals_performer_rejected
        """
        project = _active_single_line_project()
        set_clock("2026-08-20T09:00:00Z")
        visit = create_performed_visit(
            project["id"], visit_date="2026-08-20", purpose="PROGRESS_OBSERVATION",
            performed_by_user_id=USER_ARCH_2,
        )
        resp = api.create_field_report(
            {"site_visit_id": visit["id"], "issued_by_user_id": USER_ARCH_2,
             "conformance_summary": "CONFORMING", "nonconforming_work_flag": False},
            make_architect_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_REPORT_ISSUER_IS_PERFORMER, 422)
        current = get_success_data(api.get_site_visit(visit["id"], make_architect_headers()))
        assert current["status"] == "PERFORMED"


class TestClearNonconformanceInvalidStates:
    def _flagged_report_and_pending_clearing_visit(self, api):
        """V1 REPORT_ISSUED flagged nonconforming; V2 performed but not reported."""
        project = _active_single_line_project()
        set_clock("2026-08-20T09:00:00Z")
        visit1, report1 = create_report_issued_visit(
            project["id"], visit_date="2026-08-20", purpose="PAYMENT_VERIFICATION",
            conformance_summary="NONCONFORMING", nonconforming_work_flag=True,
        )
        set_clock("2026-08-21T09:00:00Z")
        visit2 = create_performed_visit(
            project["id"], visit_date="2026-08-21", purpose="PROGRESS_OBSERVATION",
        )
        return project, visit1, report1, visit2

    def test_clear_nonconformance_with_invalid_visit_returns_422(self, api):
        """PRD 3.3: "The clearing visit must belong to the same project, be in
        `REPORT_ISSUED`, have its own field report with `nonconforming_work_flag`
        false, and have a `performed_at` at or after the flagged visit's
        `performed_at`; any shortfall is rejected with
        `ERR_NONCONFORMANCE_CLEARANCE_VISIT_INVALID` (HTTP 422)."

        Design: Corner/validations/clear_nonconformance_with_invalid_visit_returns_422
        """
        project, visit1, report1, visit2 = (
            self._flagged_report_and_pending_clearing_visit(api))
        resp = api.clear_nonconformance(
            report1["id"], {"clearing_visit_id": visit2["id"]},
            make_architect_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_NONCONFORMANCE_CLEARANCE_VISIT_INVALID, 422)
        current = get_success_data(api.get_field_report(report1["id"], make_architect_headers()))
        assert current["nonconformance_status"] == "OPEN"

    def test_clear_nonconformance_on_unflagged_report_returns_invalid_state(self, api):
        """PRD 3.3: "Clearing against a report whose `nonconformance_status` is
        not `OPEN` fails with `ERR_FIELD_REPORT_INVALID_STATE` (HTTP 409)."

        Design: Corner/validations/clear_nonconformance_on_unflagged_report_returns_invalid_state
        """
        project = _active_single_line_project()
        set_clock("2026-08-20T09:00:00Z")
        visit, report = create_report_issued_visit(
            project["id"], visit_date="2026-08-20", purpose="PROGRESS_OBSERVATION",
        )
        assert report["nonconformance_status"] == "NONE"
        resp = api.clear_nonconformance(
            report["id"], {"clearing_visit_id": visit["id"]},
            make_architect_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_FIELD_REPORT_INVALID_STATE, 409)
        current = get_success_data(api.get_field_report(report["id"], make_architect_headers()))
        assert current["nonconformance_status"] == "NONE"


class TestClearNonconformanceHappyPath:
    def _flagged_and_cleared_scenario(self, api):
        """V1 flagged nonconforming; V2 conforming REPORT_ISSUED; app against V1."""
        from test_helpers import create_payment_application
        project = _active_single_line_project()
        set_clock("2026-08-20T09:00:00Z")
        visit1, report1 = create_report_issued_visit(
            project["id"], visit_date="2026-08-20", purpose="PAYMENT_VERIFICATION",
            conformance_summary="NONCONFORMING", nonconforming_work_flag=True,
        )
        set_clock("2026-08-21T09:00:00Z")
        visit2, _report2 = create_report_issued_visit(
            project["id"], visit_date="2026-08-21", purpose="PROGRESS_OBSERVATION",
        )
        application = create_payment_application(
            project["id"], visit1["id"], period_ending_date="2026-08-31",
            lines=[{"sov_line_code": "A", "work_completed_this_period_cents": 1000000,
                    "stored_materials_cents": 0}],
        )
        return project, visit1, report1, visit2, application

    def test_clear_records_clearing_visit_and_moves_to_cleared(self, api):
        """PRD 3.3: "A successful clearance records the supplied identifier on the
        report's `clearing_visit_id` and moves `nonconformance_status` to
        `CLEARED`, which is effectively terminal for the sub-lifecycle."

        Design: Corner/validations/clear_nonconformance_happy_path_clears_and_unblocks_certify
        """
        project, visit1, report1, visit2, application = (
            self._flagged_and_cleared_scenario(api))
        cleared = validate_success(api.clear_nonconformance(
            report1["id"], {"clearing_visit_id": visit2["id"]},
            make_architect_headers(),
        ), 200)
        assert cleared["nonconformance_status"] == "CLEARED"
        assert cleared["clearing_visit_id"] == visit2["id"]

    def test_certify_succeeds_after_clearance(self, api):
        """PRD 2.10: "certification is blocked when the verification visit's field
        report flags nonconforming work that has not been cleared, returning
        `ERR_NONCONFORMANCE_NOT_CLEARED` (HTTP 409)." and PRD 3.5: "A successful
        certification stamps `certified_at` from the clock, records the certifier
        in `certified_by_user_id`, moves the application to `CERTIFIED`".

        Design: Corner/validations/clear_nonconformance_happy_path_clears_and_unblocks_certify
        """
        project, visit1, report1, visit2, application = (
            self._flagged_and_cleared_scenario(api))
        api.clear_nonconformance(
            report1["id"], {"clearing_visit_id": visit2["id"]},
            make_architect_headers(),
        )
        certified = validate_success(
            api.certify_payment_application(application["id"], make_architect_headers()), 200)
        assert certified["status"] == "CERTIFIED"
        assert certified["certified_current_due_cents"] == 900000
