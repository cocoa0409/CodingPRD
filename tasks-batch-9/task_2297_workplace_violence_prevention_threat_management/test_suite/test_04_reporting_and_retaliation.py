"""The report's two independent status dimensions and the anti-retaliation hold."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assert_case_state,
    assert_protection,
    assert_report_dimensions,
    assert_severity,
    assert_total_count,
    build_protective_action,
    build_retaliation_update,
    drive_case_to_monitoring,
    read_case,
    read_report,
    setup_escalated_report,
    setup_filed_report,
)


def _allege_retaliation(api: ApiClient, ctx):
    """The reporter alleges retaliation over the schedule change that followed her report."""
    return get_success_data(
        api.create_retaliation_update(
            ctx["report"]["id"],
            build_retaliation_update(
                "ALLEGE",
                statement="My supervisor cut my hours the day after I filed the report.",
            ),
            ctx["headers"]["employee"],
        )
    )


class TestIndependentStatusDimensions:
    """Triage and retaliation advance on one row without disturbing each other."""

    def test_each_dimension_advances_without_moving_the_other(self, api: ApiClient) -> None:
        """ALLEGE, ESCALATE, OPEN_REVIEW, the decision and DISMISS each move exactly one dimension.

        PRD: "These two dimensions are **independent**: a report may sit in `triage_status` `SUBSTANTIATED` while its `retaliation_status` is still `NOT_ALLEGED`, and equally may have a substantiated retaliation claim while its triage disposition is `CLOSED_NO_ACTION`."
        Design: Difficulty/non_linear_state_machine/incident_report_triage_and_retaliation_dimensions_advance_independently
        """
        ctx = setup_filed_report(api)

        alleged = _allege_retaliation(api, ctx)
        assert_report_dimensions(alleged, triage_status="NEW", retaliation_status="ALLEGED")
        assert alleged["retaliation_claimant_employee_id"] == ctx["rep"]["id"]

        ctx = setup_escalated_report(api, ctx)
        assert_report_dimensions(
            ctx["report"], triage_status="ESCALATED", retaliation_status="ALLEGED"
        )

        under_review = get_success_data(
            api.create_retaliation_update(
                ctx["report"]["id"],
                build_retaliation_update(
                    "OPEN_REVIEW", statement="Opening an HR review of the schedule change."
                ),
                ctx["headers"]["hr_partner"],
            )
        )
        assert_report_dimensions(
            under_review, triage_status="ESCALATED", retaliation_status="UNDER_REVIEW"
        )

        ctx = drive_case_to_monitoring(api, ctx)
        assert_report_dimensions(
            read_report(api, ctx), triage_status="SUBSTANTIATED", retaliation_status="UNDER_REVIEW"
        )

        dismissed = get_success_data(
            api.create_retaliation_update(
                ctx["report"]["id"],
                build_retaliation_update(
                    "DISMISS",
                    statement="Hours were cut plant-wide before the report was filed.",
                ),
                ctx["headers"]["hr_partner"],
            )
        )
        assert_report_dimensions(
            dismissed, triage_status="SUBSTANTIATED", retaliation_status="UNSUBSTANTIATED"
        )

    def test_severity_classification_survives_every_retaliation_transition(
        self, api: ApiClient
    ) -> None:
        """A weaponed first-aid coworker report reads 50 points and CRITICAL before and after the claim.

        PRD: "The total is a whole number and its bands are exact: `severity_class` is `CRITICAL` when `severity_points` is at least 40, `SERIOUS` when it is at least 20 but below 40, and `MINOR` below 20."
        Design: Difficulty/non_linear_state_machine/incident_report_triage_and_retaliation_dimensions_advance_independently
        """
        ctx = setup_filed_report(api)
        assert_severity(ctx["report"], 50, "CRITICAL", log_required=True)

        alleged = _allege_retaliation(api, ctx)
        assert_severity(alleged, 50, "CRITICAL")

        ctx = setup_escalated_report(api, ctx)
        assert ctx["report"]["triaged_by_employee_id"] == ctx["so"]["id"]
        ctx = drive_case_to_monitoring(api, ctx)

        final = read_report(api, ctx)
        assert_severity(final, 50, "CRITICAL", log_required=True)
        assert final["retaliation_claimant_employee_id"] == ctx["rep"]["id"]


class TestAntiRetaliationHoldPrecedence:
    """The hold is checked ahead of the protection-window rule."""

    def _monitoring_case_with_live_allegation(self, api: ApiClient):
        ctx = setup_filed_report(api)
        _allege_retaliation(api, ctx)
        ctx = setup_escalated_report(api, ctx)
        return drive_case_to_monitoring(api, ctx)

    def _retaliatory_schedule_change(self, api: ApiClient, ctx):
        return api.create_case_action(
            build_protective_action(
                ctx["case"]["id"],
                "SCHEDULE_CHANGE",
                ctx["rep"]["id"],
                "2026-09-01T00:00:00Z",
                "2026-09-02T00:00:00Z",
                note="Move the claimant to the night rotation.",
            ),
            ctx["headers"]["security_coordinator"],
        )

    def test_hold_outranks_the_protection_window_rule(self, api: ApiClient) -> None:
        """A schedule change on the claimant lying wholly after the window reports the retaliation code.

        PRD: "Such a request is refused with `ERR_ANTI_RETALIATION_HOLD`, and it is refused **ahead of** every interval-window, escort-booking and area-capacity rule, so a measure that is simultaneously retaliatory and scheduled entirely outside the case's protection window reports the retaliation code rather than the window code."
        Design: Difficulty/priority_pair_validation_conflict/anti_retaliation_hold_outranks_protection_window_rule
        """
        ctx = self._monitoring_case_with_live_allegation(api)

        response = self._retaliatory_schedule_change(api, ctx)

        validate_error(response, ApiErrorId.ANTI_RETALIATION_HOLD, 409)
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.MEASURE_OUTSIDE_PROTECTION_WINDOW
        )

    def test_refused_measure_leaves_no_case_action_and_no_coverage_change(
        self, api: ApiClient
    ) -> None:
        """The rejected schedule change writes nothing: no row, no open action, the gap still 336.00 hours.

        PRD: "While any report has a `retaliation_status` of `ALLEGED`, `UNDER_REVIEW` or `SUBSTANTIATED`, no adverse protective measure — a schedule change or an access restriction — may name that report's `retaliation_claimant_employee_id` as its subject."
        Design: Difficulty/priority_pair_validation_conflict/anti_retaliation_hold_outranks_protection_window_rule
        """
        ctx = self._monitoring_case_with_live_allegation(api)

        validate_error(
            self._retaliatory_schedule_change(api, ctx), ApiErrorId.ANTI_RETALIATION_HOLD, 409
        )

        assert_total_count(
            api.list_case_actions(
                ctx["headers"]["security_coordinator"], {"case_id": ctx["case"]["id"]}
            ),
            0,
        )
        case = read_case(api, ctx)
        assert_case_state(case, status="MONITORING", open_action_count=0)
        assert_protection(case, coverage_gap_hours=336.00, protection_status="GAP")
        report = read_report(api, ctx)
        assert_report_dimensions(report, retaliation_status="ALLEGED")
        assert report["retaliation_claimant_employee_id"] == ctx["rep"]["id"]
