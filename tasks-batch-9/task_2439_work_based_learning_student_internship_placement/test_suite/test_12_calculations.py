"""Derivation coverage: the first-match eligibility ladder and its strict
thresholds, the ten-point conditional penalty that leaves approved sites alone,
the headline rate over an empty cohort, and the coverage clause that sends an
unpaid placement's incident to the district.
"""

from test_helpers import (
    COORDINATOR,
    OFFICER,
    REVIEWER,
    api_client,
    create_student_payload,
    decide_safety_review_payload,
    file_safety_review,
    read_incident,
    read_partner,
    read_placement,
    read_worksite,
    recruit_employer_partner,
    register_reviewed_worksite,
    register_worksite,
    report_incident,
    set_clock,
    setup_active_placement,
    substantiate_incident,
    update_student_academics_payload,
    validate_success,
)

YARDLEY_COMPOSITES = {
    "legal_name": "Yardley Composites",
    "naics_code": "326199",
    "industry_sector": "MANUFACTURING",
    "workers_comp_policy_no": "WC-10131",
}
ZEPHYR_CLINIC = {
    "legal_name": "Zephyr Animal Clinic",
    "naics_code": "541940",
    "industry_sector": "HEALTHCARE",
    "workers_comp_policy_no": "WC-10141",
}

WREN_KOVAC = {
    "full_name": "Wren Kovac",
    "birth_date": "2011-01-19",
    "grade_level": 9,
    "gpa": 1.50,
    "attendance_rate": 0.80,
    "student_learner_certificate": False,
}
XAN_PETROSYAN = {
    "full_name": "Xan Petrosyan",
    "birth_date": "2010-12-02",
    "grade_level": 9,
    "gpa": 2.00,
    "attendance_rate": 0.90,
    "student_learner_certificate": True,
}
BO_NAKASHIMA = {
    "full_name": "Bo Nakashima",
    "birth_date": "2009-03-03",
    "grade_level": 12,
    "gpa": 3.50,
    "attendance_rate": 0.97,
    "student_learner_certificate": False,
}

UNPAID_PLACEMENT = {
    "pay_classification": "UNPAID",
    "hourly_wage_cents": 0,
    "stipend_total_cents": 0,
    "scheduled_weekly_hours": 10.00,
    "start_on": "2026-09-14",
    "end_on": "2026-12-18",
    "credit_target_credits": 0.50,
    "credit_award_mode": "HOURS_BASED",
    "required_evaluation_cycles": 1,
    "transportation_mode": "DISTRICT_BUS",
    "commute_round_trip_miles": 0.00,
}


class TestEligibilityLadder:
    def test_a_ninth_grader_stops_at_the_grade_clause_before_any_other(self):
        """The derivation walks four clauses in this fixed order and takes the first that
        matches: if `grade_level` is below 10, the status is `INELIGIBLE_GRADE`; otherwise if
        `gpa` is below 2.00, the status is `INELIGIBLE_ACADEMIC`; otherwise if
        `attendance_rate` is below 0.90, the status is `INELIGIBLE_ATTENDANCE`; otherwise the
        status is `ELIGIBLE`.

        Design: Corner/calculations/student_eligibility_returns_the_first_matching_clause_only
        """
        set_clock("2026-09-01T08:00:00Z")

        student = validate_success(
            api_client.create_student(
                create_student_payload(**WREN_KOVAC), COORDINATOR
            ),
            expected_status=201,
        )

        assert student["eligibility_status"] == "INELIGIBLE_GRADE"
        assert student["active_placement_count"] == 0

    def test_a_gpa_of_exactly_two_and_attendance_of_exactly_nine_tenths_are_eligible(self):
        """All three comparisons are strict, so a `gpa` of exactly 2.00 and an
        `attendance_rate` of exactly 0.90 are both eligible, and a ninth-grader is ineligible
        on grade even if their grades and attendance are perfect. Academic standing is
        restated by supplying `grade_level`, `gpa` and `attendance_rate` together, which also
        increments the student's `version` by 1.

        Design: Corner/calculations/eligibility_thresholds_are_strict_less_than_at_two_point_zero_and_zero_point_nine
        """
        set_clock("2026-09-01T08:00:00Z")
        student = validate_success(
            api_client.create_student(
                create_student_payload(**XAN_PETROSYAN), COORDINATOR
            ),
            expected_status=201,
        )

        restated = validate_success(
            api_client.update_student_academics(
                student["id"],
                update_student_academics_payload(10, 2.00, 0.90),
                COORDINATOR,
            )
        )

        assert restated["grade_level"] == 10
        assert float(restated["gpa"]) == 2.00
        assert float(restated["attendance_rate"]) == 0.90
        assert restated["eligibility_status"] == "ELIGIBLE"


class TestSafetyScorePenalties:
    def test_only_the_conditional_worksite_costs_the_partner_ten_points(self):
        """Subtract 10 points for each of the partner's worksites whose `safety_status` is
        `CONDITIONAL`. Otherwise, if at least one worksite of the partner has `safety_status`
        of `APPROVED` or `CONDITIONAL`, the posture is `ELIGIBLE`.

        Design: Corner/calculations/safety_score_penalty_counts_conditional_worksites_and_ignores_approved_ones
        """
        set_clock("2026-09-07T08:00:00Z")
        partner = recruit_employer_partner(**YARDLEY_COMPOSITES)
        conditional_site, _review_a = register_reviewed_worksite(
            partner["id"],
            decision="CONDITIONAL",
            review_overrides={"hazard_findings_count": 1},
            site_name="Yardley Layup Bay",
            address_line="8 Yardley Rd",
            hazard_class="LIMITED_HAZARD",
            has_power_machinery=True,
            max_concurrent_students=1,
        )
        approved_site = register_worksite(
            partner["id"],
            site_name="Yardley Trim Room",
            address_line="10 Yardley Rd",
            max_concurrent_students=2,
        )
        review_b = file_safety_review(approved_site["id"], approved_site["version"])

        decided = validate_success(
            api_client.decide_safety_review(
                review_b["id"], decide_safety_review_payload("APPROVED"), REVIEWER
            )
        )

        assert decided["status"] == "APPROVED"
        assert read_worksite(conditional_site["id"])["safety_status"] == "CONDITIONAL"
        assert read_worksite(approved_site["id"])["safety_status"] == "APPROVED"

        stored_partner = read_partner(partner["id"])
        assert stored_partner["safety_score"] == 90
        assert stored_partner["posture"] == "ELIGIBLE"


class TestOutcomeRateOverAnEmptyCohort:
    def test_an_empty_cohort_reports_a_zero_rate_rather_than_an_error(self):
        """An empty cohort is not an error: when the denominator is 0 the report returns a
        `positive_rate` of exactly 0.0000 with a `denominator` of 0.

        Design: Corner/calculations/outcome_rate_over_an_empty_cohort_returns_zero_not_an_error
        """
        set_clock("2026-09-01T08:00:00Z")

        report = validate_success(
            api_client.get_outcome_rate_report(
                OFFICER, {"from_date": "2026-01-01", "to_date": "2026-06-30"}
            )
        )

        assert report["numerator"] == 0
        assert report["denominator"] == 0
        assert float(report["positive_rate"]) == 0.0


class TestCoverageDeterminationClauses:
    def test_an_unpaid_placement_under_a_rider_lands_on_district_liability(self):
        """Otherwise, if the placement's `pay_classification` is `UNPAID` or `STIPEND` and the
        governing agreement's `insurance_rider` is true, the determination is
        `DISTRICT_LIABILITY`. At `MINOR` or `MODERATE` severity, substantiation flags without
        stopping: every `Placement` at that worksite whose `lifecycle_status` is `PROPOSED` or
        `ACTIVE` and whose `compliance_status` is `PENDING_REVIEW` or `CLEARED` moves to
        `FLAGGED`, and nothing else cascades. Subtract 30 points for each such report at
        `MODERATE` severity.

        Design: Corner/calculations/unpaid_placement_with_rider_determines_district_liability_coverage
        """
        scenario = setup_active_placement(
            clock="2026-09-14T08:00:00Z",
            course_code="VET-210",
            credit_hours_target=60.00,
            partner_overrides=ZEPHYR_CLINIC,
            worksite_overrides={
                "site_name": "Zephyr Kennel Wing",
                "address_line": "2 Zephyr Ln",
                "max_concurrent_students": 2,
            },
            supervisor_overrides={"full_name": "Ada Sorensen", "max_student_load": 2},
            student_overrides=BO_NAKASHIMA,
            permit_class="MINOR_16_17",
            placement_overrides=dict(UNPAID_PLACEMENT),
        )
        incident = report_incident(
            scenario,
            "2026-09-14T10:00:00Z",
            severity="MODERATE",
            injury_type="LACERATION",
            description="Student scratched while restraining a cat",
        )
        substantiate_incident(incident["id"])

        closed = validate_success(
            api_client.record_incident_coverage(incident["id"], {}, OFFICER)
        )

        assert closed["coverage_determination"] == "DISTRICT_LIABILITY"
        assert read_incident(incident["id"])["status"] == "CLOSED"

        partner = read_partner(scenario.partner_id)
        assert partner["substantiated_moderate_count"] == 1
        assert partner["safety_score"] == 70
        assert partner["posture"] == "ELIGIBLE"

        placement = read_placement(scenario.placement_id)
        assert placement["compliance_status"] == "FLAGGED"
        assert placement["lifecycle_status"] == "ACTIVE"
