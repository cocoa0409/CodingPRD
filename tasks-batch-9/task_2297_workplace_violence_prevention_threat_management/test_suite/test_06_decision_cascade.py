"""The four-link cascade an elevated-risk decision drives from case to plan."""

from test_helpers import (
    ApiClient,
    assert_case_state,
    assert_log_elements_present,
    assert_penalty_band_from_rounded_subtotal,
    assert_plan_metrics,
    assert_plan_state,
    assert_protection,
    assert_readiness,
    assert_report_dimensions,
    assert_risk_scores,
    read_case,
    read_case_log_entries,
    read_plan,
    read_report,
    read_worksite,
    setup_monitoring_case,
)


class TestElevatedRiskCascade:
    """One decision moves the case, the report, the log register, the worksite and the plan."""

    def test_decision_substantiates_the_report_and_appends_exactly_one_log_entry(
        self, api: ApiClient
    ) -> None:
        """Hops one to three: MONITORING at 60.94, a SUBSTANTIATED report and one six-element entry.

        PRD: "The linked incident report moves `triage_status` `ESCALATED` → `SUBSTANTIATED`. Because the report is now substantiated and its `log_required` is true, exactly one violent incident log entry is appended, carrying six of the eight required regulatory elements."
        Design: Difficulty/transitive_cascade/decide_elevated_risk_cascades_four_hops_to_plan_review_due
        """
        ctx = setup_monitoring_case(api)

        case = read_case(api, ctx)
        assert_case_state(case, status="MONITORING")
        assert_risk_scores(
            case, consensus=60.94, risk_band="HIGH", disposition="ELEVATED_RISK"
        )
        assert_report_dimensions(read_report(api, ctx), triage_status="SUBSTANTIATED")

        entries = read_case_log_entries(api, ctx)
        assert len(entries) == 1, "the decision must append exactly one log entry"
        entry = entries[0]
        assert entry["worksite_id"] == ctx["worksite"]["id"]
        assert entry["incident_report_id"] == ctx["report"]["id"]
        assert entry["case_id"] == ctx["case"]["id"]
        assert entry["incident_at"] == "2026-07-30T14:00:00Z"
        assert entry["work_area_name"] == "Front Desk"
        assert entry["incident_type"] == "TYPE_3_COWORKER"
        assert entry["perpetrator_class"] == "COWORKER"
        assert entry["injury_level"] == "FIRST_AID"
        assert entry["law_enforcement_notified"] is False
        assert entry["consequence_narrative"] is None
        assert entry["controls_summary"] is None
        assert entry["weapon_involved"] is True
        assert entry["retention_status"] == "ACTIVE"
        assert entry["retention_expiry_date"] == "2031-07-30T14:00:00Z"
        assert entry["superseded_flag"] is False
        assert entry["supersedes_entry_id"] is None
        assert_log_elements_present(entry, 6)

    def test_the_new_entry_makes_the_worksite_high_risk_and_pushes_the_plan_to_review_due(
        self, api: ApiClient
    ) -> None:
        """Hop four: one entry flips `high_risk_flag`, restricts the plan and re-bars readiness at 85.00.

        PRD: "And because `high_risk_flag` flipped, the worksite's `ACTIVE` plan moves to `REVIEW_DUE`, its `compliance_posture` becomes `RESTRICTED`, and `inspection_ready` is re-evaluated against 85.00."
        Design: Difficulty/transitive_cascade/decide_elevated_risk_cascades_four_hops_to_plan_review_due
        """
        ctx = setup_monitoring_case(api)

        worksite = read_worksite(api, ctx["worksite"]["id"])
        assert worksite["violent_incident_count_12mo"] == 1
        assert worksite["high_risk_flag"] is True

        plan = read_plan(api, ctx)
        assert_plan_state(plan, status="REVIEW_DUE", compliance_posture="RESTRICTED")
        assert_plan_metrics(
            plan,
            hazard_coverage_pct=100.00,
            training_compliance_pct=100.00,
            log_completeness_pct=75.00,
            drills_completed_12mo=0,
            unmitigated_hazard_count=1,
            overdue_action_count=0,
        )
        assert_readiness(
            plan,
            subtotal=80.00,
            penalty_band="ADEQUATE",
            penalty_points=4.80,
            score=75.20,
            inspection_ready=False,
        )
        assert_penalty_band_from_rounded_subtotal(plan)

        case = read_case(api, ctx)
        assert case["protection_window_start"] == "2026-08-01T00:00:00Z"
        assert case["protection_window_end"] == "2026-08-15T00:00:00Z"
        assert_protection(case, coverage_gap_hours=336.00, protection_status="GAP")
        assert_case_state(case, open_action_count=0)
