"""License-order obligations, the compliance sweep and annual compliance reporting."""
import pytest

from test_helpers import (
    U_LICENSEE_A,
    U_LICENSEE_CERT,
    api_client,
    assert_postures,
    certify_obligation,
    file_annual_report,
    file_application,
    list_obligations,
    make_licensee_headers,
    new_project,
    obligation_of_type,
    read_application,
    read_obligation,
    read_order,
    read_project,
    run_sweep,
    schedule_obligation,
    schedule_payload,
    set_clock,
    setup_licensed_project,
    validate_error,
)

LICENSEE_HEADERS = make_licensee_headers(U_LICENSEE_A)
DAM_ONE_ACTIVITY = dict(
    dam_code="D1",
    hazard_class="HIGH",
    inspection_interval_months=12,
    eap_exercise_required=False,
    max_concurrent_field_activities=1,
)
DAM_TWO_ACTIVITIES = dict(DAM_ONE_ACTIVITY, max_concurrent_field_activities=2)


def _licensed_project(order_number, dam, project_name):
    """A project walked to an EFFECTIVE order over one dam and one certification condition."""
    return setup_licensed_project(
        order_number=order_number,
        dams=[dam],
        site_overrides=dict(river_mile=10.0),
        project_name=project_name,
        installed_capacity_mw=24.0,
        base_annual_generation_mwh=250000,
        license_expiration_date="2033-12-31",
    )


def _attempt_schedule(obligation_id, start, end):
    """Schedule without pre-validating, so a rejection can be inspected."""
    return api_client.schedule_obligation(
        obligation_id, schedule_payload(start, end), LICENSEE_HEADERS
    )


class TestAnnualReportBasisDivergence:
    def _order_with_one_certified_and_two_overdue_obligations(self):
        ctx = _licensed_project("ORD-1", DAM_ONE_ACTIVITY, "Cascade Falls II")
        pme = obligation_of_type(ctx["obligations"], "PME_IMPLEMENTATION")
        schedule_obligation(pme["id"], "2027-01-05", "2027-01-20")
        set_clock("2027-01-10T00:00:00Z")
        ctx["pme_obligation"] = certify_obligation(pme["id"], user_id=U_LICENSEE_CERT)
        set_clock("2028-09-01T00:00:00Z")
        ctx["project"] = run_sweep(ctx["project"]["id"])
        return ctx

    def test_the_two_bases_assess_different_obligation_sets_for_the_same_year(self):
        """One order, one period year, two windows: three obligations against two.

        PRD §3.9: "Under `CALENDAR`, the window runs from the first of January of `period_year` through the thirty-first of December of `period_year`."
        PRD §3.9: "Under `LICENSE_ANNIVERSARY`, the window starts on the month and day of the order's `effective_date` in `period_year` and runs to the day before the next anniversary — that is, the start date plus 12 months, minus one day."

        Design: Difficulty/dual_variant_calc/annual_report_calendar_vs_anniversary_basis_assess_different_sets
        """
        ctx = self._order_with_one_certified_and_two_overdue_obligations()
        order_id = ctx["order"]["id"]
        assert ctx["order"]["effective_date"] == "2026-08-01"

        calendar = file_annual_report(order_id, "CALENDAR", 2027)
        anniversary = file_annual_report(order_id, "LICENSE_ANNIVERSARY", 2027)

        assert calendar["assessed_obligation_count"] == 3
        assert calendar["noncompliant_obligation_count"] == 2
        assert calendar["compliance_score"] == pytest.approx(33.33, abs=0.01)
        assert anniversary["assessed_obligation_count"] == 2
        assert anniversary["noncompliant_obligation_count"] == 2
        assert anniversary["compliance_score"] == pytest.approx(0.00, abs=0.01)

    def test_the_divergence_comes_from_the_window_and_not_from_any_status_change(self):
        """The obligations are untouched by reporting and the flag outlives both reports.

        PRD §3.9: "Filing also stores `last_report_basis`, `last_report_period_year` and `last_report_filed_at` from the logical clock, and increments the order's `version`."
        PRD §3.9: "Reporting is a cure path, permitted even while the project is already `FROZEN`, and it never clears `COMPLIANCE_FLAGGED` by itself — only certifying the last outstanding violation does that."

        Design: Difficulty/dual_variant_calc/annual_report_calendar_vs_anniversary_basis_assess_different_sets
        """
        ctx = self._order_with_one_certified_and_two_overdue_obligations()
        order_id = ctx["order"]["id"]
        assert_postures(ctx["project"], regulatory_posture="FROZEN")

        file_annual_report(order_id, "CALENDAR", 2027)
        file_annual_report(order_id, "LICENSE_ANNIVERSARY", 2027)

        order = read_order(order_id)
        assert order["last_report_basis"] == "LICENSE_ANNIVERSARY"
        assert order["last_report_period_year"] == 2027
        assert order["compliance_state"] == "COMPLIANCE_FLAGGED"
        certified = read_obligation(ctx["pme_obligation"]["id"])
        assert certified["status"] == "CERTIFIED"
        assert certified["due_date"] == "2027-02-01"
        assert certified["certified_at"].startswith("2027-01-10T00:00:00")
        for obligation_type in ("DAM_SAFETY_INSPECTION", "PUBLIC_SAFETY_SIGNAGE"):
            dam_obligation = obligation_of_type(
                list_obligations(order_id), obligation_type
            )
            assert dam_obligation["status"] == "OVERDUE"
            assert dam_obligation["due_date"] == "2027-08-01"


class TestSweepCascadeIntoSuspendedAmendment:
    def _licensed_project_with_a_pending_amendment(self):
        ctx = _licensed_project("ORD-2", DAM_TWO_ACTIVITIES, "Amendment Bend")
        ctx["amendment"] = file_application(
            ctx["project"]["id"],
            application_type="AMENDMENT",
            amends_order_id=ctx["order"]["id"],
            filing_note="capacity amendment",
        )
        set_clock("2028-09-01T00:00:00Z")
        return ctx

    def test_the_sweep_marks_every_due_obligation_overdue_and_flags_the_order(self):
        """A no-payload sweep turns three PENDING articles into three open violations.

        PRD §3.9: "First, every obligation belonging to one of the project's non-superseded orders whose status is `PENDING` or `SCHEDULED` and whose `due_date` is earlier than the logical clock's date moves to `OVERDUE`, with `overdue_marked_at` stamped from the logical clock and its own `version` incremented; each owning order's `open_violation_count` is recomputed and an order carrying at least one violation moves `EFFECTIVE → COMPLIANCE_FLAGGED`, incrementing that order's `version`."

        Design: Difficulty/transitive_cascade/sweep_overdue_cascades_into_suspended_amendment_application
        """
        ctx = self._licensed_project_with_a_pending_amendment()
        assert {o["status"] for o in ctx["obligations"]} == {"PENDING"}

        run_sweep(ctx["project"]["id"])

        obligations = list_obligations(ctx["order"]["id"])
        assert len(obligations) == 3
        for obligation in obligations:
            assert obligation["status"] == "OVERDUE"
            assert obligation["overdue_marked_at"].startswith("2028-09-01T00:00:00")
        order = read_order(ctx["order"]["id"])
        assert order["compliance_state"] == "COMPLIANCE_FLAGGED"
        assert order["open_violation_count"] == 3

    def test_the_freeze_suspends_the_amendment_the_sweep_never_names(self):
        """The fourth level of the cascade reaches an application outside the request.

        PRD §2.8: "The posture is `FROZEN` when any of the following holds: the project's `wqc_status` is `DENIED`, or its `compliance_flag_count` is greater than zero, or its `timeline_posture` is `DELINQUENT`."
        PRD §3.9: "Third, the project's `timeline_posture` is recomputed against its outstanding milestone, its `compliance_flag_count` is recomputed, and then `regulatory_posture` is recomputed from all its inputs; where the result is `FROZEN`, every application of the project whose `filing_status` is `FILED`, `UNDER_REVIEW` or `DEFICIENT` moves to `SUSPENDED`."

        Design: Difficulty/transitive_cascade/sweep_overdue_cascades_into_suspended_amendment_application
        """
        ctx = self._licensed_project_with_a_pending_amendment()
        assert ctx["amendment"]["filing_status"] == "FILED"

        swept = run_sweep(ctx["project"]["id"])

        assert swept["compliance_flag_count"] == 1
        assert_postures(swept, regulatory_posture="FROZEN")
        assert read_application(ctx["amendment"]["id"])["filing_status"] == "SUSPENDED"
        assert read_application(ctx["application"]["id"])["filing_status"] == "LICENSED"
        assert read_project(ctx["project"]["id"])["last_sweep_at"].startswith(
            "2028-09-01T00:00:00"
        )


class TestTimelineSlackBoundary:
    def _project_with_an_outstanding_pre_application_deadline(self):
        set_clock("2026-08-01T00:00:00Z")
        return new_project(
            project_name="Slack Day Dam",
            installed_capacity_mw=8.0,
            base_annual_generation_mwh=40000,
            license_expiration_date="2033-12-31",
        )

    def test_one_hundred_and_eighty_days_of_slack_is_at_risk_and_one_more_is_not(self):
        """The same sweep reads ON_TRACK at 181 days and AT_RISK at exactly 180.

        PRD §2.7: "The **pre-application document deadline** falls 66 months — five and a half years — before expiration."
        PRD §2.7: "When the count is zero or more but no greater than 180 days, the posture is `AT_RISK`; the milestone date itself therefore yields a count of zero and reads `AT_RISK`, not `DELINQUENT`."

        Design: Difficulty/boundary_precision_check/timeline_slack_exactly_at_at_risk_boundary_is_not_delinquent
        """
        project = self._project_with_an_outstanding_pre_application_deadline()
        assert_postures(project, timeline_posture="ON_TRACK", regulatory_posture="OPEN")

        set_clock("2028-01-01T00:00:00Z")
        one_day_of_room = run_sweep(project["id"])
        set_clock("2028-01-02T00:00:00Z")
        at_the_boundary = run_sweep(project["id"])

        assert_postures(
            one_day_of_room, timeline_posture="ON_TRACK", regulatory_posture="OPEN"
        )
        assert_postures(
            at_the_boundary, timeline_posture="AT_RISK", regulatory_posture="RESTRICTED"
        )

    def test_a_negative_slack_of_one_day_freezes_the_project(self):
        """Passing the milestone by a single day is DELINQUENT and drives the freeze.

        PRD §2.7: "When that count is negative — the milestone date is already in the past — the posture is `DELINQUENT`."
        PRD §3.9: "Fourth, `last_sweep_at` is stamped from the logical clock and the project's `version` is incremented."

        Design: Difficulty/boundary_precision_check/timeline_slack_exactly_at_at_risk_boundary_is_not_delinquent
        """
        project = self._project_with_an_outstanding_pre_application_deadline()
        set_clock("2028-01-02T00:00:00Z")
        run_sweep(project["id"])

        set_clock("2028-07-01T00:00:00Z")
        overdue = run_sweep(project["id"])

        assert_postures(
            overdue, timeline_posture="DELINQUENT", regulatory_posture="FROZEN"
        )
        assert overdue["stage"] == "PRE_FILING"
        assert overdue["last_sweep_at"].startswith("2028-07-01T00:00:00")


class TestEmptyReportPeriod:
    def _flagged_order_with_no_obligation_due_in_2029(self):
        ctx = _licensed_project("ORD-4", DAM_TWO_ACTIVITIES, "Empty Window Dam")
        set_clock("2029-02-01T00:00:00Z")
        ctx["project"] = run_sweep(ctx["project"]["id"])
        return ctx

    def test_an_empty_assessed_set_scores_exactly_one_hundred(self):
        """No obligation falls inside the 2029 calendar window, so the score is 100.00.

        PRD §3.9: "The **assessed** set is every obligation of the order whose `due_date` falls inside the window, inclusive of both bounds, and whose status is anything other than `WAIVED`."
        PRD §3.9: "`compliance_score` is 100 multiplied by the assessed count minus the noncompliant count, divided by the assessed count, rounded half up to two decimal places; when the assessed count is zero the score is exactly 100.00, never 0.00."

        Design: Difficulty/boundary_precision_check/empty_report_period_scores_exactly_one_hundred_without_clearing_flags
        """
        ctx = self._flagged_order_with_no_obligation_due_in_2029()
        assert ctx["order"]["article_count"] == 3
        assert_postures(ctx["project"], regulatory_posture="FROZEN")

        report = file_annual_report(ctx["order"]["id"], "CALENDAR", 2029)

        assert report["assessed_obligation_count"] == 0
        assert report["noncompliant_obligation_count"] == 0
        assert report["compliance_score"] == pytest.approx(100.00, abs=0.01)

    def test_a_perfect_empty_window_leaves_the_flag_and_the_freeze_in_place(self):
        """Three OVERDUE articles stand behind a report reading 100.00.

        PRD §3.9: "Reporting is a cure path, permitted even while the project is already `FROZEN`, and it never clears `COMPLIANCE_FLAGGED` by itself — only certifying the last outstanding violation does that."

        Design: Difficulty/boundary_precision_check/empty_report_period_scores_exactly_one_hundred_without_clearing_flags
        """
        ctx = self._flagged_order_with_no_obligation_due_in_2029()

        report = file_annual_report(ctx["order"]["id"], "CALENDAR", 2029)

        assert report["compliance_state"] == "COMPLIANCE_FLAGGED"
        order = read_order(ctx["order"]["id"])
        assert order["open_violation_count"] == 3
        assert order["last_report_basis"] == "CALENDAR"
        assert order["last_report_period_year"] == 2029
        assert_postures(
            read_project(ctx["project"]["id"]), regulatory_posture="FROZEN"
        )


class TestDamActivityCapacity:
    def _dam_with_one_scheduled_inspection(self):
        ctx = _licensed_project("ORD-5", DAM_ONE_ACTIVITY, "Capacity Dam")
        ctx["inspection"] = obligation_of_type(
            ctx["obligations"], "DAM_SAFETY_INSPECTION"
        )
        ctx["signage"] = obligation_of_type(ctx["obligations"], "PUBLIC_SAFETY_SIGNAGE")
        ctx["inspection"] = schedule_obligation(
            ctx["inspection"]["id"], "2027-05-01", "2027-05-31"
        )
        return ctx

    def test_closed_windows_sharing_one_endpoint_day_exceed_a_capacity_of_one(self):
        """A second activity starting on the first one's last day overruns the dam.

        PRD §3.9: "For a dam-bound obligation — one of type `DAM_SAFETY_INSPECTION`, `PUBLIC_SAFETY_SIGNAGE` or `EAP_EXERCISE` — the count of dam-bound obligations at that same dam whose status is `SCHEDULED` and whose closed activity windows overlap the requested closed window, plus the one now being scheduled, must not exceed that dam's `max_concurrent_field_activities`; exceeding it is rejected with `ERR_DAM_ACTIVITY_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/dam_activity_capacity_counts_closed_windows_touching_at_one_day
        """
        ctx = self._dam_with_one_scheduled_inspection()
        assert ctx["inspection"]["status"] == "SCHEDULED"
        assert ctx["inspection"]["due_date"] == "2027-08-01"
        assert ctx["signage"]["due_date"] == "2027-08-01"

        response = _attempt_schedule(ctx["signage"]["id"], "2027-05-31", "2027-06-30")

        validate_error(response, "ERR_DAM_ACTIVITY_CAPACITY_EXCEEDED", 409)
        assert read_obligation(ctx["signage"]["id"])["status"] == "PENDING"

    def test_starting_a_day_later_clears_the_capacity_and_schedules(self):
        """Moving the window one day forward frees the dam and the retry is accepted.

        PRD §3.9: "The `Licensee` schedules an obligation by supplying an `activity_window_start` and an `activity_window_end` — a **closed** interval, both ends inclusive, with the start no later than the end — plus an optional `schedule_note`."
        PRD §3.9: "Both paths store the window and increment the obligation's `version`, and both apply the same two checks."

        Design: Difficulty/resource_temporal_overlap/dam_activity_capacity_counts_closed_windows_touching_at_one_day
        """
        ctx = self._dam_with_one_scheduled_inspection()
        validate_error(
            _attempt_schedule(ctx["signage"]["id"], "2027-05-31", "2027-06-30"),
            "ERR_DAM_ACTIVITY_CAPACITY_EXCEEDED",
            409,
        )

        scheduled = schedule_obligation(
            ctx["signage"]["id"], "2027-06-01", "2027-06-30"
        )

        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["activity_window_start"] == "2027-06-01"
        assert scheduled["activity_window_end"] == "2027-06-30"
        untouched = read_obligation(ctx["inspection"]["id"])
        assert untouched["activity_window_end"] == "2027-05-31"
        assert read_order(ctx["order"]["id"])["open_violation_count"] == 0
