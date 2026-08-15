"""Disproportionality monitoring: INTERIM/FINAL variants, ratios, flagging."""
from test_helpers import (
    CLOCK_TODAY,
    TEST_USERS,
    ApiErrorId,
    advance_cycle,
    api_client,
    bulk_enroll,
    cast_vote,
    create_case,
    create_site,
    create_student,
    create_transfer_honor_case,
    enter_measure,
    finalize_case,
    get_case,
    open_band_review,
    set_clock,
    setup_cycle_in_state,
    validate_error,
    validate_success,
)

GC = TEST_USERS["gifted_coordinator_headers"]


def _honor_transfer(cycle_id, student_id):
    return create_transfer_honor_case(
        student_id, cycle_id, external_district_name="ExtDist",
        external_identified_on="2026-03-01")


def _group(report, name):
    for g in report["group_metrics"]:
        if g["demographic_group"] == name:
            return g
    raise AssertionError(f"group {name} missing from group_metrics: "
                         f"{report['group_metrics']}")


def _rate(group_metric):
    """Read the group's identification rate.

    PRD §3.8 pins the VALUE rule verbatim ("Each group's identification rate
    is its identified count divided by its enrolled count, rounded half-up to
    four decimal places") but never names the per-group JSON key inside
    `group_metrics`, so the key spelling is not uniquely derivable from PRD
    (`rate` and `identification_rate` are both faithful renderings of the
    prose). Accept either; the exact 4-dp value assertion below is unchanged.
    """
    for key in ("rate", "identification_rate"):
        if key in group_metric:
            return float(group_metric[key])
    raise AssertionError(
        f"identification rate missing from group metric: {group_metric}")


def _build_projection_roster():
    """Roster for the INTERIM-vs-FINAL projection scenario:
    50 WHITE (40 bulk + 10 individual) and 25 BLACK (20 bulk + 5 individual),
    all grade 3; 10 WHITE and 4 BLACK honored via TRANSFER_HONOR; the fifth
    BLACK student scored 99/90/88 into the review band."""
    set_clock(CLOCK_TODAY)
    site = create_site()
    bulk_enroll(site["id"], 3, "WHITE", 40)
    bulk_enroll(site["id"], 3, "BLACK", 20)
    cycle, profile = setup_cycle_in_state("OPEN")
    for i in range(1, 11):
        stu = create_student(site["id"], student_number=f"W{i:02d}",
                             legal_name=f"W {i:02d}", grade_level=3,
                             demographic_group="WHITE",
                             primary_guardian_user_id=f"guard-w{i:02d}")
        _honor_transfer(cycle["id"], stu["id"])
    black_cases = []
    for i in range(1, 6):
        stu = create_student(site["id"], student_number=f"B{i:02d}",
                             legal_name=f"B {i:02d}", grade_level=3,
                             demographic_group="BLACK",
                             primary_guardian_user_id=f"guard-b{i:02d}")
        if i <= 4:
            _honor_transfer(cycle["id"], stu["id"])
        else:
            case = create_case(stu["id"], cycle["id"],
                               pathway="UNIVERSAL_SCREEN")
            enter_measure(case["id"], "ABILITY", 99)
            enter_measure(case["id"], "ACHIEVEMENT", 90)
            enter_measure(case["id"], "RATING_SCALE", 88)
            black_cases.append(case)
    advance_cycle(cycle["id"], "SCORING")
    band_case = finalize_case(black_cases[0]["id"])
    assert band_case["status"] == "AWAITING_COMMITTEE"
    advance_cycle(cycle["id"], "REVIEW")
    return {"site": site, "cycle": cycle, "band_case": band_case}


class TestInterimVsFinalProjection:
    def test_interim_projection_counts_pipeline_states(self, api):
        """PRD §3.8: "`FINAL` counts students with a case in this cycle in
        `IDENTIFIED` status — the audit view — while `INTERIM` additionally
        counts `AWAITING_COMMITTEE` and `APPEAL_PENDING`, a forward-looking
        projection of the pipeline."
        PRD §3.8: "The **reference group** is the group with the largest
        enrolled count, ties broken by `demographic_group` name ascending."

        Design: Difficulty/dual_variant_calc/disproportionality_interim_vs_final_projection
        """
        ctx = _build_projection_roster()
        resp = api.get_disproportionality_report(
            ctx["cycle"]["id"], GC, params={"variant": "INTERIM"})
        report = validate_success(resp, 200)
        assert report["variant"] == "INTERIM"
        assert report["reference_group"] == "WHITE"
        # 14 IDENTIFIED (10 WHITE + 4 BLACK) + 1 AWAITING_COMMITTEE (BLACK).
        assert report["total_identified"] == 15
        white = _group(report, "WHITE")
        assert white["enrolled"] == 50
        assert white["identified"] == 10
        assert _rate(white) == 0.2000
        assert float(white["risk_ratio"]) == 1.000
        black = _group(report, "BLACK")
        assert black["enrolled"] == 25
        assert black["identified"] == 5
        assert _rate(black) == 0.2000
        assert float(black["risk_ratio"]) == 1.000

    def test_final_view_counts_identified_only(self, api):
        """PRD §3.8: "`FINAL` counts students with a case in this cycle in
        `IDENTIFIED` status — the audit view — while `INTERIM` additionally
        counts `AWAITING_COMMITTEE` and `APPEAL_PENDING`".

        Design: Difficulty/dual_variant_calc/disproportionality_interim_vs_final_projection
        """
        ctx = _build_projection_roster()
        cycle_id = ctx["cycle"]["id"]
        # Deny the band case, then finalize the cycle.
        review = open_band_review(ctx["band_case"]["id"])
        cast_vote(review["id"], "DENY", "cm-1")
        cast_vote(review["id"], "DENY", "cm-2")
        advance_cycle(cycle_id, "FINALIZED")
        resp = api.get_disproportionality_report(
            cycle_id, GC, params={"variant": "FINAL"})
        report = validate_success(resp, 200)
        assert report["variant"] == "FINAL"
        assert report["total_identified"] == 14
        black = _group(report, "BLACK")
        assert black["identified"] == 4
        assert _rate(black) == 0.1600
        assert float(black["risk_ratio"]) == 0.800


class TestRiskRatioFlagBoundary:
    def _build_three_group_roster(self):
        """50 WHITE (10 identified), 25 BLACK (4 identified), 25 HISPANIC
        (3 identified), all grade 3; cycle advanced to FINALIZED."""
        set_clock(CLOCK_TODAY)
        site = create_site()
        bulk_enroll(site["id"], 3, "WHITE", 40)
        bulk_enroll(site["id"], 3, "BLACK", 21)
        bulk_enroll(site["id"], 3, "HISPANIC", 22)
        cycle, _ = setup_cycle_in_state("OPEN")
        plan = (("WHITE", 10), ("BLACK", 4), ("HISPANIC", 3))
        n = 0
        for group, count in plan:
            for _ in range(count):
                n += 1
                stu = create_student(
                    site["id"], student_number=f"{group[:1]}{n:03d}",
                    legal_name=f"{group} {n}", grade_level=3,
                    demographic_group=group,
                    primary_guardian_user_id=f"guard-{n}")
                _honor_transfer(cycle["id"], stu["id"])
        advance_cycle(cycle["id"], "SCORING")
        advance_cycle(cycle["id"], "REVIEW")
        advance_cycle(cycle["id"], "FINALIZED")
        return cycle

    def test_risk_ratio_exactly_at_flag_threshold_not_flagged(self, api):
        """PRD §3.8: "A group is flagged `UNDER_REPRESENTED` when its rounded
        ratio is strictly below 0.800 **and** its enrolled count is at least
        10 — a ratio of exactly 0.800 is not flagged, and small cells below
        10 enrolled students never flag regardless of ratio."
        PRD §3.8: "Each group's risk ratio is its rounded rate divided by the
        reference group's rounded rate, rounded half-up to three decimal
        places".

        Design: Difficulty/boundary_precision_check/risk_ratio_exactly_at_flag_threshold_not_flagged
        """
        cycle = self._build_three_group_roster()
        resp = api.get_disproportionality_report(
            cycle["id"], GC, params={"variant": "FINAL"})
        report = validate_success(resp, 200)
        assert report["reference_group"] == "WHITE"
        assert report["total_identified"] == 17
        black = _group(report, "BLACK")
        assert black["enrolled"] == 25
        assert black["identified"] == 4
        assert _rate(black) == 0.1600
        assert float(black["risk_ratio"]) == 0.800
        assert black["flagged"] is False, "0.800 is not < 0.800"

    def test_risk_ratio_below_threshold_flagged(self, api):
        """PRD §3.8: "A group is flagged `UNDER_REPRESENTED` when its rounded
        ratio is strictly below 0.800 **and** its enrolled count is at least
        10".
        PRD §3.8: "The response carries `cycle_id`, the `variant`, the
        `reference_group`, the `total_identified` summed across groups, the
        per-group `group_metrics`, and the `flagged_groups` list."

        Design: Difficulty/boundary_precision_check/risk_ratio_exactly_at_flag_threshold_not_flagged
        """
        cycle = self._build_three_group_roster()
        resp = api.get_disproportionality_report(
            cycle["id"], GC, params={"variant": "FINAL"})
        report = validate_success(resp, 200)
        white = _group(report, "WHITE")
        assert white["enrolled"] == 50
        assert white["identified"] == 10
        assert _rate(white) == 0.2000
        assert float(white["risk_ratio"]) == 1.000
        hispanic = _group(report, "HISPANIC")
        assert hispanic["enrolled"] == 25
        assert hispanic["identified"] == 3
        assert _rate(hispanic) == 0.1200
        assert float(hispanic["risk_ratio"]) == 0.600
        assert hispanic["flagged"] is True
        assert report["flagged_groups"] == ["HISPANIC"]


class TestInterimConservation:
    def _build_two_student_pipeline(self):
        """Two grade-3 WHITE students: W1 honored (IDENTIFIED), W2 scored
        into the band (AWAITING_COMMITTEE) with a BAND_REVIEW open; cycle in
        REVIEW."""
        set_clock(CLOCK_TODAY)
        site = create_site()
        cycle, _ = setup_cycle_in_state("OPEN")
        stu1 = create_student(site["id"], student_number="ST-J1",
                              legal_name="Stu J1", grade_level=3,
                              demographic_group="WHITE",
                              primary_guardian_user_id="guard-j1")
        _honor_transfer(cycle["id"], stu1["id"])
        stu2 = create_student(site["id"], student_number="ST-J2",
                              legal_name="Stu J2", grade_level=3,
                              demographic_group="WHITE",
                              primary_guardian_user_id="guard-j2")
        case2 = create_case(stu2["id"], cycle["id"], pathway="UNIVERSAL_SCREEN")
        enter_measure(case2["id"], "ABILITY", 99)
        enter_measure(case2["id"], "ACHIEVEMENT", 90)
        enter_measure(case2["id"], "RATING_SCALE", 88)
        advance_cycle(cycle["id"], "SCORING")
        finalized = finalize_case(case2["id"])
        assert finalized["status"] == "AWAITING_COMMITTEE"
        advance_cycle(cycle["id"], "REVIEW")
        review = open_band_review(case2["id"])
        return {"cycle": cycle, "case2": case2, "review": review}

    def test_interim_total_conserved_across_decision(self, api):
        """PRD §3.8: "`FINAL` counts students with a case in this cycle in
        `IDENTIFIED` status — the audit view — while `INTERIM` additionally
        counts `AWAITING_COMMITTEE` and `APPEAL_PENDING`, a forward-looking
        projection of the pipeline."

        Design: Difficulty/compensating_invariant/interim_projection_conserved_across_decision
        """
        ctx = self._build_two_student_pipeline()
        cycle_id = ctx["cycle"]["id"]
        before = validate_success(
            api.get_disproportionality_report(cycle_id, GC,
                                              params={"variant": "INTERIM"}),
            200)
        assert before["total_identified"] == 2, (
            "1 IDENTIFIED + 1 AWAITING_COMMITTEE both count in the projection")

        cast_vote(ctx["review"]["id"], "QUALIFY", "cm-1")
        cast_vote(ctx["review"]["id"], "QUALIFY", "cm-2")

        after = validate_success(
            api.get_disproportionality_report(cycle_id, GC,
                                              params={"variant": "INTERIM"}),
            200)
        assert after["total_identified"] == 2, (
            "the QUALIFY decision converts a projected identification into a "
            "real one; the INTERIM total is conserved")
        assert after["total_identified"] == before["total_identified"]

    def test_interim_partition_sum_matches_total(self, api):
        """PRD §3.8: "The response carries `cycle_id`, the `variant`, the
        `reference_group`, the `total_identified` summed across groups, the
        per-group `group_metrics`, and the `flagged_groups` list."

        Design: Difficulty/compensating_invariant/interim_projection_conserved_across_decision
        """
        ctx = self._build_two_student_pipeline()
        cycle_id = ctx["cycle"]["id"]
        before = validate_success(
            api.get_disproportionality_report(cycle_id, GC,
                                              params={"variant": "INTERIM"}),
            200)
        assert sum(g["identified"] for g in before["group_metrics"]) == \
            before["total_identified"] == 2
        assert _group(before, "WHITE")["enrolled"] == 2

        cast_vote(ctx["review"]["id"], "QUALIFY", "cm-1")
        cast_vote(ctx["review"]["id"], "QUALIFY", "cm-2")

        after = validate_success(
            api.get_disproportionality_report(cycle_id, GC,
                                              params={"variant": "INTERIM"}),
            200)
        assert sum(g["identified"] for g in after["group_metrics"]) == \
            after["total_identified"] == 2
        assert get_case(ctx["case2"]["id"])["status"] == "IDENTIFIED"


class TestReportGating:
    def test_report_variants_gated_by_cycle_state(self, api):
        """PRD §3.8: "Availability is state-gated: `INTERIM` requires the
        cycle in `REVIEW` or `FINALIZED`, while `FINAL` is allowed only once
        the cycle is `FINALIZED`; asking earlier fails with
        `ERR_INVALID_CYCLE_STATE`."

        Design: Corner/validations/report_variants_gated_by_cycle_state
        """
        create_site()
        cycle, _ = setup_cycle_in_state("SCORING")
        resp = api.get_disproportionality_report(
            cycle["id"], GC, params={"variant": "INTERIM"})
        validate_error(resp, ApiErrorId.ERR_INVALID_CYCLE_STATE.value)
        advance_cycle(cycle["id"], "REVIEW")
        resp2 = api.get_disproportionality_report(
            cycle["id"], GC, params={"variant": "FINAL"})
        validate_error(resp2, ApiErrorId.ERR_INVALID_CYCLE_STATE.value)
