"""Inclusive boundaries: eighteen graduate hours, and a 0.7000 experience score."""

from test_helpers import (
    ApiErrorId,
    assert_assignment_verdict,
    assert_fields,
    assert_score,
    assignment_payload,
    justification_decision_payload,
    make_assignment,
    make_credentialed_faculty,
    make_program_dean_headers,
    make_reviewed_justification,
    make_section,
    make_verified_credential,
    open_remediation,
    read_assignment,
    read_faculty,
    read_section,
    TEST_USERS,
    validate_error,
    validate_success,
)


def _coursework_boundary_state(env):
    """One instructor at exactly eighteen aligned graduate hours, one at seventeen."""
    dana = make_credentialed_faculty(
        "Dana Reyes",
        "dana.reyes@example.edu",
        "ADJUNCT",
        env.prog_df_id,
        "MASTERS",
        env.pr_id,
        "State University",
        graduate_credit_hours_in_discipline=30,
    )["faculty"]
    make_verified_credential(
        dana["id"],
        "NON_DEGREE_GRADUATE",
        env.journ_id,
        "State University",
        graduate_credit_hours_in_discipline=18,
    )
    sam = make_credentialed_faculty(
        "Sam Okafor",
        "sam.okafor@example.edu",
        "ADJUNCT",
        env.prog_cw_id,
        "NON_DEGREE_GRADUATE",
        env.journ_id,
        "State University",
        graduate_credit_hours_in_discipline=17,
    )["faculty"]
    section = make_section(
        env.prog_cw_id,
        env.term_id,
        env.journ_id,
        "JOUR102",
        "Reporting Practicum",
        credit_hours=3,
        meeting_days=["TUE"],
        meeting_start_minute=540,
        meeting_end_minute=620,
    )
    return {"dana_id": dana["id"], "sam_id": sam["id"], "section": section}


class TestCourseworkHourBoundary:
    def test_exactly_eighteen_aligned_hours_qualifies(self, api, env):
        """PRD §3.4: "The **coursework test** sums
        `graduate_credit_hours_in_discipline` over exactly those eligible records
        whose effective discipline aligns with the section discipline at 0.70 or
        above, and passes when that sum reaches the section discipline's
        `min_graduate_credit_hours` — 18 hours by default."

        Design: Difficulty/boundary_precision_check/coursework_hours_exactly_at_eighteen_qualifies_seventeen_does_not
        """
        state = _coursework_boundary_state(env)
        section = state["section"]

        assignment = validate_success(
            api.create_course_assignment(
                assignment_payload(
                    section["id"], state["dana_id"], section["version"]
                ),
                make_program_dean_headers(env.prog_cw_id),
            ),
            201,
        )

        assert_assignment_verdict(
            assignment,
            status="VERIFIED_QUALIFIED",
            qualification_basis="COURSEWORK_18_HOUR",
            exception_code=None,
            alignment_score=1.0000,
        )
        assert read_faculty(state["dana_id"])["assigned_credit_hours"] == 3

    def test_seventeen_hours_falls_short_of_the_threshold(self, api, env):
        """PRD §3.4: "`DEGREE_LEVEL_INSUFFICIENT`, when the credential test failed
        and `alignment_score` is at least 0.70."

        Design: Difficulty/boundary_precision_check/coursework_hours_exactly_at_eighteen_qualifies_seventeen_does_not
        """
        state = _coursework_boundary_state(env)
        section = state["section"]
        make_assignment(
            section["id"],
            state["dana_id"],
            env.prog_cw_id,
            expected_section_version=section["version"],
        )
        refreshed = read_section(section["id"])["version"]

        assignment = validate_success(
            api.create_course_assignment(
                assignment_payload(
                    section["id"],
                    state["sam_id"],
                    refreshed,
                    assignment_role="CO_INSTRUCTOR",
                ),
                make_program_dean_headers(env.prog_cw_id),
            ),
            201,
        )

        assert_assignment_verdict(
            assignment,
            status="EXCEPTION_FLAGGED",
            qualification_basis="NONE",
            exception_code="DEGREE_LEVEL_INSUFFICIENT",
            alignment_score=1.0000,
        )
        assert read_faculty(state["sam_id"])["assigned_credit_hours"] == 3

    def test_the_first_assignment_advances_the_section_by_one_version(self, api, env):
        """PRD §2.7: "Both writes also advance their parent: creating an assignment
        increments the `CourseSection.version`, and issuing a contract increments the
        `FacultyMember.version`."

        Design: Difficulty/boundary_precision_check/coursework_hours_exactly_at_eighteen_qualifies_seventeen_does_not
        """
        state = _coursework_boundary_state(env)
        section = state["section"]

        make_assignment(
            section["id"],
            state["dana_id"],
            env.prog_cw_id,
            expected_section_version=section["version"],
        )

        assert read_section(section["id"])["version"] == section["version"] + 1, (
            "the section is the concurrency parent, so one accepted assignment "
            "advances it by exactly one"
        )


def _experience_boundary_state(env):
    """Two remediating assignments with justifications either side of 0.70."""
    alex = make_credentialed_faculty(
        "Alex Stone",
        "alex.stone@example.edu",
        "ADJUNCT",
        env.prog_df_id,
        "MASTERS",
        env.pr_id,
        "Coastal University",
        graduate_credit_hours_in_discipline=33,
    )["faculty"]
    sec_a = make_section(
        env.prog_df_id,
        env.term_id,
        env.journ_id,
        "JOUR101",
        "News Writing",
        credit_hours=3,
        meeting_days=["MON"],
        meeting_start_minute=540,
        meeting_end_minute=620,
    )
    sec_b = make_section(
        env.prog_df_id,
        env.term_id,
        env.journ_id,
        "JOUR104",
        "Data Journalism",
        credit_hours=3,
        meeting_days=["TUE"],
        meeting_start_minute=540,
        meeting_end_minute=620,
    )
    asn_a = make_assignment(sec_a["id"], alex["id"], env.prog_df_id)
    asn_b = make_assignment(sec_b["id"], alex["id"], env.prog_df_id)
    open_remediation(asn_a["id"], env.prog_df_id, "TESTED_EXPERIENCE_PENDING")
    open_remediation(asn_b["id"], env.prog_df_id, "TESTED_EXPERIENCE_PENDING")
    just_at = make_reviewed_justification(
        asn_a["id"],
        env.prog_df_id,
        documented_years_experience=8,
        industry_certification_level="PRACTITIONER",
        alternative_credential_codes=["APR"],
        supervisor_attestation_on_file=True,
    )
    just_below = make_reviewed_justification(
        asn_b["id"],
        env.prog_df_id,
        documented_years_experience=8,
        industry_certification_level="PRACTITIONER",
        alternative_credential_codes=[],
        supervisor_attestation_on_file=True,
    )
    return {
        "asn_at": asn_a["id"],
        "asn_below": asn_b["id"],
        "just_at": just_at,
        "just_below": just_below,
    }


class TestTestedExperienceScoreBoundary:
    def test_a_score_of_exactly_seven_tenths_is_approvable(self, api, env):
        """PRD §3.5: "Both thresholds are inclusive: exactly three years is enough,
        and a score of exactly 0.7000 is approvable."

        Design: Difficulty/boundary_precision_check/tested_experience_score_exactly_at_threshold_approves_one_notch_below_rejects
        """
        state = _experience_boundary_state(env)
        assert_score(
            state["just_at"]["tested_experience_score"],
            0.7000,
            "tested_experience_score",
        )

        decided = validate_success(
            api.decide_justification(
                state["just_at"]["id"],
                justification_decision_payload("APPROVE"),
                TEST_USERS["analyst_2"],
            )
        )

        assert_fields(decided, status="APPROVED")
        assert_fields(
            read_assignment(state["asn_at"]),
            status="VERIFIED_QUALIFIED",
            qualification_basis="TESTED_EXPERIENCE",
        )

    def test_one_notch_below_the_threshold_is_rejected(self, api, env):
        """PRD §3.5: "And `documented_years_experience` must be at least 3 **while**
        `tested_experience_score` is at least 0.70, or the decision fails with
        `ERR_TESTED_EXPERIENCE_INSUFFICIENT`."

        Design: Difficulty/boundary_precision_check/tested_experience_score_exactly_at_threshold_approves_one_notch_below_rejects
        """
        state = _experience_boundary_state(env)
        assert_score(
            state["just_below"]["tested_experience_score"],
            0.6500,
            "tested_experience_score",
        )

        response = api.decide_justification(
            state["just_below"]["id"],
            justification_decision_payload("APPROVE"),
            TEST_USERS["analyst_2"],
        )

        validate_error(response, ApiErrorId.ERR_TESTED_EXPERIENCE_INSUFFICIENT)
        unchanged = validate_success(
            api.get_justification(state["just_below"]["id"], TEST_USERS["analyst_2"])
        )
        assert_fields(unchanged, status="UNDER_REVIEW", decided_by_user_id=None)
        assert_fields(
            read_assignment(state["asn_below"]), status="REMEDIATION_IN_PROGRESS"
        )
