"""Readiness thresholds, the drill half-credit, protective interval merging and the conditional quorum."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    ApiClient,
    ApiErrorId,
    add_team_seat,
    assert_case_action,
    assert_case_state,
    assert_hazard_assessment,
    assert_plan_metrics,
    assert_plan_state,
    assert_protection,
    assert_readiness,
    assert_readiness_threshold_applied,
    assert_risk_scores,
    assert_severity,
    assert_sweep_counters,
    build_convene,
    build_drill_execution,
    build_hazard_validation,
    build_protective_action,
    move_clock,
    read_case,
    read_plan,
    run_daily_sweep,
    setup_active_plan,
    setup_case_with_core_seats,
    setup_drilled_plan,
    setup_escalated_report,
    setup_filed_report,
    setup_monitoring_case,
    setup_open_case,
    setup_screened_plan,
    setup_submitted_plan,
)

#: A hotline call about an ex-partner loitering at shift change: no weapon, no injury.
DOMESTIC_REPORT = {
    "channel": "HOTLINE",
    "occurred_at": "2026-07-26T18:00:00Z",
    "narrative": "A former partner has been waiting outside the building at shift change for three days.",
    "incident_type": "TYPE_4_DOMESTIC",
    "weapon_involved": False,
    "injury_level": "NONE",
}


def _add_schedule_change(
    api: ApiClient, ctx, starts_at: str, ends_at: str, note: str
):
    """Move the subject's rota away from the protected employee for one half-open interval."""
    payload = build_protective_action(
        ctx["case"]["id"],
        "SCHEDULE_CHANGE",
        ctx["subj"]["id"],
        starts_at,
        ends_at,
        note=note,
    )
    return get_success_data(
        api.create_case_action(payload, ctx["headers"]["security_coordinator"])
    )


class TestReadinessThresholdBoundary:
    """The restricted bar is inclusive, so a mitigated plan can survive the periodic review flip."""

    def test_a_review_due_plan_at_exactly_eighty_five_stays_inspection_ready(
        self, api: ApiClient
    ) -> None:
        """Validation clears the tier-1 hazard, so the score is 85.00 with no penalty and clears the higher bar.

        PRD: "Both boundaries are inclusive: a score of exactly 85.00 on a `RESTRICTED` plan is ready."
        Design: Corner/calculations/inspection_readiness_exactly_eighty_five_flags_a_restricted_plan_ready
        """
        ctx = setup_screened_plan(api)
        validated = get_success_data(
            api.validate_hazard_assessment(
                ctx["hazard_assessment"]["id"],
                build_hazard_validation(),
                ctx["headers"]["site_manager"],
            )
        )
        assert_hazard_assessment(
            validated,
            hazard_score=39.00,
            control_tier="TIER_2_ADMINISTRATIVE",
            score_variant="VALIDATED",
            status="VALIDATED",
            mitigation_verified=True,
        )
        ctx = setup_submitted_plan(api, ctx)
        ctx = setup_active_plan(api, ctx)
        before = read_plan(api, ctx)
        assert_plan_state(before, status="ACTIVE", compliance_posture="OPEN")
        assert_plan_metrics(before, unmitigated_hazard_count=0)
        assert_readiness(
            before,
            subtotal=85.00,
            penalty_band="ADEQUATE",
            penalty_points=0.00,
            score=85.00,
            inspection_ready=True,
        )

        assert move_clock(api, "2027-08-02T00:00:00Z") == "2027-08-02T00:00:00Z"
        counters = run_daily_sweep(api)

        assert_sweep_counters(counters, plans_review_due_count=1, plans_rescored_count=1)
        after = read_plan(api, ctx)
        assert_plan_state(after, status="REVIEW_DUE", compliance_posture="RESTRICTED")
        assert_readiness(
            after,
            subtotal=85.00,
            penalty_band="ADEQUATE",
            penalty_points=0.00,
            score=85.00,
            inspection_ready=True,
        )
        assert_readiness_threshold_applied(after)


class TestDrillComponentHalfCredit:
    """Two drills a year make the drill weight a two-step ramp rather than a boolean."""

    def test_the_first_credited_drill_is_worth_half_the_drill_weight(
        self, api: ApiClient
    ) -> None:
        """One credited drill adds 7.50 and lifts the band to STRONG; the second saturates the ratio at 1.

        PRD: "The drill component is 15 points multiplied by the smaller of 1 and the ratio of `drills_completed_12mo` to the two drills required per year — so two credited drills in the trailing year earn the full 15 points and one earns half."
        Design: Corner/calculations/drill_component_uses_required_drills_per_year_two
        """
        ctx = setup_drilled_plan(api)
        before = read_plan(api, ctx)
        assert_plan_metrics(before, drills_completed_12mo=0, unmitigated_hazard_count=1)
        assert_readiness(
            before,
            subtotal=85.00,
            penalty_band="ADEQUATE",
            penalty_points=5.10,
            score=79.90,
            inspection_ready=True,
        )

        first = get_success_data(
            api.execute_drill(
                ctx["drill_one"]["id"],
                build_drill_execution(12, findings_count=2),
                ctx["headers"]["safety_officer"],
            )
        )

        assert first["participation_pct"] == 60.00
        assert first["credited"] is True
        halfway = read_plan(api, ctx)
        assert_plan_metrics(halfway, drills_completed_12mo=1)
        assert_readiness(
            halfway,
            subtotal=92.50,
            penalty_band="STRONG",
            penalty_points=1.85,
            score=90.65,
            inspection_ready=True,
        )

        second = get_success_data(
            api.execute_drill(
                ctx["drill_two"]["id"],
                build_drill_execution(20, findings_count=0),
                ctx["headers"]["safety_officer"],
            )
        )

        assert second["participation_pct"] == 100.00
        saturated = read_plan(api, ctx)
        assert_plan_metrics(saturated, drills_completed_12mo=2)
        assert_readiness(
            saturated,
            subtotal=100.00,
            penalty_band="STRONG",
            penalty_points=2.00,
            score=98.00,
            inspection_ready=True,
        )
        assert_plan_state(saturated, compliance_posture="OPEN")


class TestProtectiveCoverageMerge:
    """Coverage is computed by clipping each measure to the window and merging what survives."""

    def test_two_touching_measures_merge_and_close_the_window(self, api: ApiClient) -> None:
        """A zero-length gap is no gap, so 336.00 falls to 168.00 and then to exactly 0.00.

        PRD: "**Adjacent intervals merge**, because a zero-length gap is no gap — two measures where one ends exactly when the next begins together cover the whole span."
        Design: Corner/calculations/adjacent_protective_intervals_merge_to_full_coverage
        """
        ctx = setup_monitoring_case(api)
        assert_protection(
            read_case(api, ctx), coverage_gap_hours=336.00, protection_status="GAP"
        )

        first = _add_schedule_change(
            api,
            ctx,
            "2026-08-01T00:00:00Z",
            "2026-08-08T00:00:00Z",
            "Subject moved to the first-half day shift away from the protected employee.",
        )
        assert_case_action(first, status="SCHEDULED", duration_minutes=10080)
        assert_protection(
            read_case(api, ctx), coverage_gap_hours=168.00, protection_status="GAP"
        )

        second = _add_schedule_change(
            api,
            ctx,
            "2026-08-08T00:00:00Z",
            "2026-08-15T00:00:00Z",
            "Second-half rota continues the separation with no break in cover.",
        )

        assert_case_action(second, duration_minutes=10080)
        case = read_case(api, ctx)
        assert_protection(case, coverage_gap_hours=0.00, protection_status="COVERED")
        assert_case_state(case, status="MONITORING", open_action_count=0)

    def test_a_measure_starting_before_the_window_counts_only_its_tail(
        self, api: ApiClient
    ) -> None:
        """duration_minutes keeps the raw eight days while only the 24 hours inside the window reduce the gap.

        PRD: "Each candidate is clipped to the window — its start becomes the later of its own `starts_at` and the window start, its end becomes the earlier of its own `ends_at` and the window end — and any candidate that collapses to nothing after clipping is dropped."
        Design: Corner/calculations/protective_interval_clipped_to_the_protection_window
        """
        ctx = setup_monitoring_case(api)

        early = _add_schedule_change(
            api,
            ctx,
            "2026-07-25T00:00:00Z",
            "2026-08-02T00:00:00Z",
            "Rota change that started the week before the window opened.",
        )

        assert_case_action(early, status="SCHEDULED", duration_minutes=11520)
        assert_protection(
            read_case(api, ctx), coverage_gap_hours=312.00, protection_status="GAP"
        )

        later = _add_schedule_change(
            api,
            ctx,
            "2026-08-03T00:00:00Z",
            "2026-08-15T00:00:00Z",
            "Rota change resuming after a one-day handover break.",
        )

        assert_case_action(later, duration_minutes=17280)
        assert_protection(
            read_case(api, ctx), coverage_gap_hours=24.00, protection_status="GAP"
        )


class TestConditionalQuorumForDomesticIncidents:
    """The required discipline set is read off the incident, not fixed at three seats."""

    def test_the_legal_seat_alone_unlocks_the_domestic_case(self, api: ApiClient) -> None:
        """A weaponless, uninjured domestic report needs LEGAL but not CLINICAL, so the fourth seat opens round 1.

        PRD: "The same three-seat roster is therefore a quorum for an unweaponed, uninjured client-typology incident and not a quorum for an otherwise identical domestic-typology one, where `LEGAL` also becomes mandatory."
        Design: Corner/calculations/domestic_incident_quorum_requires_a_legal_seat
        """
        ctx = setup_active_plan(api)
        ctx = setup_filed_report(api, ctx, **DOMESTIC_REPORT)
        assert_severity(ctx["report"], 8, "MINOR", log_required=False)
        ctx = setup_escalated_report(api, ctx)
        ctx = setup_open_case(api, ctx)
        ctx = setup_case_with_core_seats(api, ctx)
        assert_case_state(read_case(api, ctx), status="OPEN", quorum_met=False)

        validate_error(
            api.convene_threat_case(
                ctx["case"]["id"],
                build_convene(convene_note="Attempting to convene on three seats."),
                ctx["headers"]["threat_team_lead"],
            ),
            ApiErrorId.QUORUM_NOT_MET,
            409,
        )
        ctx["seats"]["legal"] = add_team_seat(api, ctx, "legal", "LEGAL")
        assert_case_state(read_case(api, ctx), status="OPEN", quorum_met=True)

        convened = get_success_data(
            api.convene_threat_case(
                ctx["case"]["id"],
                build_convene(convene_note="Legal seated; opening round 1."),
                ctx["headers"]["threat_team_lead"],
            )
        )

        assert_case_state(
            convened, status="ASSESSING", assessment_round=1, ballot_count_current_round=0
        )
        assert_risk_scores(read_case(api, ctx), interim=4.80, risk_band="LOW")
