"""Severity bands, coverage counts, register completeness and the training pair set at their exact values."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    ApiClient,
    PROGRAM_ADMIN_HEADERS,
    add_hazard_assessment,
    assert_auto_appended_entry_is_partial,
    assert_hazard_assessment,
    assert_plan_metrics,
    assert_plan_state,
    assert_readiness,
    assert_report_dimensions,
    assert_severity,
    assert_total_count,
    build_decision,
    build_incident_report,
    build_prevention_plan,
    build_training_module,
    make_safety_officer_headers,
    read_employee,
    read_plan,
    read_worksite,
    setup_clock,
    setup_draft_plan,
    setup_deliberating_case,
    setup_employee,
    setup_programme,
    setup_screened_plan,
    setup_work_area,
    setup_worksite,
)

#: A windowless staff room with no public access, no lone working and no night shift.
BREAK_ROOM = {
    "name": "Break Room",
    "job_function": "ADMIN",
    "public_access_flag": False,
    "lone_worker_flag": False,
    "night_shift_flag": False,
    "occupancy_cap": 6,
}

#: A night-staffed goods area that the public cannot reach.
LOADING_DOCK = {
    "name": "Loading Dock",
    "job_function": "WAREHOUSE",
    "public_access_flag": False,
    "lone_worker_flag": False,
    "night_shift_flag": True,
    "occupancy_cap": 6,
}


class TestSeverityBandBoundaries:
    """The two class boundaries are inclusive, and log_required is a separate broader test."""

    def test_the_two_band_edges_are_hit_exactly_from_opposite_directions(
        self, api: ApiClient
    ) -> None:
        """Twenty points bands SERIOUS, forty bands CRITICAL, and eight stays MINOR with no log flag.

        PRD: "A weapon and no injury on a criminal-typology event scores exactly 40 and is therefore `CRITICAL`; an unweaponed first-aid coworker event scores exactly 20 and is therefore `SERIOUS`."
        Design: Corner/calculations/severity_points_exactly_at_serious_and_critical_thresholds
        """
        ctx = setup_programme(api)

        serious = get_success_data(
            api.create_incident_report(
                build_incident_report(
                    ctx["worksite"]["id"],
                    ctx["work_area"]["id"],
                    ctx["rep"]["id"],
                    channel="WEB_FORM",
                    occurred_at="2026-07-28T10:00:00Z",
                    narrative="Co-worker shoved the reporter during a handover dispute; a plaster was applied on site.",
                    incident_type="TYPE_3_COWORKER",
                    weapon_involved=False,
                    injury_level="FIRST_AID",
                ),
                ctx["headers"]["employee"],
            )
        )
        critical = get_success_data(
            api.create_incident_report(
                build_incident_report(
                    ctx["worksite"]["id"],
                    ctx["work_area"]["id"],
                    ctx["rep"]["id"],
                    channel="HOTLINE",
                    occurred_at="2026-07-29T02:00:00Z",
                    narrative="An intruder displayed a firearm at the counter overnight and left without touching anyone.",
                    incident_type="TYPE_1_CRIMINAL",
                    weapon_involved=True,
                    injury_level="NONE",
                ),
                ctx["headers"]["employee"],
            )
        )
        minor = get_success_data(
            api.create_incident_report(
                build_incident_report(
                    ctx["worksite"]["id"],
                    ctx["work_area"]["id"],
                    ctx["rep"]["id"],
                    channel="SUPERVISOR",
                    occurred_at="2026-07-27T16:00:00Z",
                    narrative="A former partner waited in the car park for a member of staff and was asked to leave.",
                    incident_type="TYPE_4_DOMESTIC",
                    weapon_involved=False,
                    injury_level="NONE",
                ),
                ctx["headers"]["employee"],
            )
        )

        assert_severity(serious, 20, "SERIOUS", log_required=True)
        assert_severity(critical, 40, "CRITICAL", log_required=True)
        assert_severity(minor, 8, "MINOR", log_required=False)
        for report in (serious, critical, minor):
            assert_report_dimensions(
                report, triage_status="NEW", retaliation_status="NOT_ALLEGED"
            )


class TestHazardCoverageDenominator:
    """Coverage is a count of distinct covered areas over the worksite's area count."""

    def test_coverage_walks_thirty_three_then_sixty_seven_then_one_hundred(
        self, api: ApiClient
    ) -> None:
        """Three areas make the percentage repeat, so each write rounds half-up at two decimals.

        PRD: "A worksite with no work areas yields 100.00; otherwise it is the numerator divided by the denominator, multiplied by 100, rounded half-up to two decimals — so one live assessment across three areas reads 33.33 and two across three reads 66.67."
        Design: Corner/calculations/hazard_coverage_percentage_over_three_areas
        """
        ctx = setup_programme(api)
        break_room = setup_work_area(api, ctx["worksite"]["id"], **BREAK_ROOM)
        loading_dock = setup_work_area(api, ctx["worksite"]["id"], **LOADING_DOCK)
        ctx = setup_draft_plan(api, ctx)
        assert_plan_metrics(read_plan(api, ctx), hazard_coverage_pct=0.00)

        front = add_hazard_assessment(api, ctx)
        assert_plan_metrics(read_plan(api, ctx), hazard_coverage_pct=33.33)
        staff_room = add_hazard_assessment(api, ctx, break_room["id"])
        assert_plan_metrics(read_plan(api, ctx), hazard_coverage_pct=66.67)
        before_third = read_plan(api, ctx)
        dock = add_hazard_assessment(api, ctx, loading_dock["id"])

        plan = read_plan(api, ctx)
        assert_plan_metrics(plan, hazard_coverage_pct=100.00, unmitigated_hazard_count=1)
        assert plan["version"] == before_third["version"] + 1
        assert_hazard_assessment(front, hazard_score=64.00, control_tier="TIER_1_ENGINEERING")
        assert_hazard_assessment(
            staff_room, hazard_score=46.00, control_tier="TIER_2_ADMINISTRATIVE"
        )
        assert_hazard_assessment(dock, hazard_score=54.00, control_tier="TIER_2_ADMINISTRATIVE")

    def test_a_superseded_assessment_leaves_both_aggregate_input_sets(
        self, api: ApiClient
    ) -> None:
        """Re-assessing one area of two neither lifts coverage above 50.00 nor double-counts the tier-1 hazard.

        PRD: "Creating an assessment for a plan-and-area pair that already has a live one is the intended way to revise: the prior assessment, whether `SCREENING` or `VALIDATED`, becomes `SUPERSEDED`, stops counting toward `hazard_coverage_pct` and `unmitigated_hazard_count`, and the area's `current_hazard_score` switches to the new screening row's score."
        Design: Corner/calculations/superseded_hazard_assessments_excluded_from_coverage
        """
        ctx = setup_programme(api)
        setup_work_area(api, ctx["worksite"]["id"], **BREAK_ROOM)
        ctx = setup_draft_plan(api, ctx)
        ctx = setup_screened_plan(api, ctx)
        first_id = ctx["hazard_assessment"]["id"]
        assert_plan_metrics(
            read_plan(api, ctx), hazard_coverage_pct=50.00, unmitigated_hazard_count=1
        )

        revision = add_hazard_assessment(
            api, ctx, reported_incident_count=6, min_staff_per_shift=1
        )

        assert_hazard_assessment(
            revision,
            hazard_score=80.00,
            control_tier="TIER_1_ENGINEERING",
            status="SCREENING",
        )
        superseded = get_success_data(
            api.get_hazard_assessment(first_id, ctx["headers"]["safety_officer"])
        )
        assert superseded["status"] == "SUPERSEDED"
        assert_plan_metrics(
            read_plan(api, ctx), hazard_coverage_pct=50.00, unmitigated_hazard_count=1
        )
        assert_total_count(
            api.list_hazard_assessments(
                ctx["headers"]["safety_officer"],
                {"plan_id": ctx["plan"]["id"], "status": "SUPERSEDED"},
            ),
            1,
        )


class TestLogCompletenessDenominator:
    """The register is vacuously complete while empty and reads element counts once populated."""

    def test_the_register_reads_one_hundred_empty_and_seventy_five_after_the_auto_entry(
        self, api: ApiClient
    ) -> None:
        """Six of eight elements on a single live entry is 75.00, not a percentage of percentages.

        PRD: "A single live entry holding six of eight elements therefore reads 75.00, and two live entries holding six and eight respectively read 87.50."
        Design: Corner/calculations/log_completeness_pct_zero_entries_then_one_partial_entry
        """
        ctx = setup_deliberating_case(api)
        assert_plan_metrics(read_plan(api, ctx), log_completeness_pct=100.00)
        assert_total_count(
            api.list_log_entries(
                ctx["headers"]["safety_officer"], {"worksite_id": ctx["worksite"]["id"]}
            ),
            0,
        )

        get_success_data(
            api.decide_threat_case(
                ctx["case"]["id"],
                build_decision("ELEVATED_RISK"),
                ctx["headers"]["threat_team_lead"],
            )
        )

        entries = assert_total_count(
            api.list_log_entries(
                ctx["headers"]["safety_officer"], {"case_id": ctx["case"]["id"]}
            ),
            1,
        )
        assert_auto_appended_entry_is_partial(entries[0])
        plan = read_plan(api, ctx)
        assert_plan_metrics(plan, log_completeness_pct=75.00, unmitigated_hazard_count=1)
        assert_plan_state(plan, status="REVIEW_DUE", compliance_posture="RESTRICTED")
        assert_readiness(
            plan,
            subtotal=80.00,
            penalty_band="ADEQUATE",
            penalty_points=4.80,
            score=75.20,
            inspection_ready=False,
        )
        assert read_worksite(api, ctx["worksite"]["id"])["high_risk_flag"] is True


class TestTrainingPairDenominator:
    """The pair set is the cross of active workers and in-scope modules, and it can be empty."""

    def test_the_percentage_is_vacuous_at_one_hundred_until_the_first_pair_exists(
        self, api: ApiClient
    ) -> None:
        """One SECURITY worker against an ADMIN module makes no pair, and the first ADMIN hire collapses it to 0.00.

        PRD: "If there are no such pairs at all the percentage is 100.00 — vacuously compliant."
        Design: Corner/calculations/training_compliance_pct_is_one_hundred_when_no_pairs_exist
        """
        setup_clock(api)
        worksite = setup_worksite(api)
        work_area = setup_work_area(api, worksite["id"])
        officer = setup_employee(
            api, worksite["id"], work_area["id"], full_name="Sofia Ortiz", job_function="SECURITY"
        )
        get_success_data(
            api.create_training_module(build_training_module(), PROGRAM_ADMIN_HEADERS)
        )
        ctx = {
            "worksite": worksite,
            "work_area": work_area,
            "headers": {"safety_officer": make_safety_officer_headers(officer["id"])},
        }

        ctx["plan"] = get_success_data(
            api.create_prevention_plan(
                build_prevention_plan(worksite["id"]), ctx["headers"]["safety_officer"]
            )
        )

        drafted = read_plan(api, ctx)
        assert_plan_state(drafted, status="DRAFT", compliance_posture="FROZEN")
        assert_plan_metrics(
            drafted,
            hazard_coverage_pct=0.00,
            training_compliance_pct=100.00,
            log_completeness_pct=100.00,
        )
        assert_readiness(
            drafted,
            subtotal=55.00,
            penalty_band="WEAK",
            penalty_points=0.00,
            score=55.00,
            inspection_ready=False,
        )

        hire = setup_employee(
            api, worksite["id"], work_area["id"], full_name="Wendy Cole", job_function="ADMIN"
        )

        after = read_plan(api, ctx)
        assert_plan_metrics(after, training_compliance_pct=0.00)
        assert_readiness(after, subtotal=30.00, penalty_band="WEAK", score=30.00)
        assert read_employee(api, hire["id"])["training_current"] is False
