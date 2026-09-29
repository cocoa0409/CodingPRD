"""The two qualification-policy variants judged against one identical dossier."""

from test_helpers import (
    assert_assignment_verdict,
    assert_fields,
    assignment_payload,
    make_credentialed_faculty,
    make_program_dean_headers,
    make_section,
    make_verified_credential,
    read_faculty,
    read_section,
    validate_success,
)


def _dual_policy_state(env):
    """Dana Reyes: a sibling-discipline master's plus eighteen aligned hours.

    Both programs sit on the same Journalism discipline, so the only thing that
    differs between the two arms is ``qualification_policy``.
    """
    built = make_credentialed_faculty(
        "Dana Reyes",
        "dana.reyes@example.edu",
        "ADJUNCT",
        env.prog_df_id,
        "MASTERS",
        env.pr_id,
        "State University",
        graduate_credit_hours_in_discipline=30,
    )
    faculty_id = built["faculty"]["id"]
    make_verified_credential(
        faculty_id,
        "NON_DEGREE_GRADUATE",
        env.journ_id,
        "State University",
        graduate_credit_hours_in_discipline=18,
    )
    sec_df = make_section(
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
    sec_cw = make_section(
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
    return {"faculty_id": faculty_id, "sec_df": sec_df, "sec_cw": sec_cw}


class TestQualificationPolicyDivergence:
    def test_degree_field_arm_flags_degree_level_insufficient(self, api, env):
        """PRD §3.4: "Under `DEGREE_FIELD` the assignment is not qualified:
        `qualification_basis` is `NONE` and `exception_code` is
        `DEGREE_LEVEL_INSUFFICIENT`."

        Design: Difficulty/dual_variant_calc/qualification_policy_degree_field_vs_coursework_18_diverge_on_identical_dossier
        """
        state = _dual_policy_state(env)
        sec_df = state["sec_df"]

        response = api.create_course_assignment(
            assignment_payload(sec_df["id"], state["faculty_id"], sec_df["version"]),
            make_program_dean_headers(env.prog_df_id),
        )
        assignment = validate_success(response, 201)

        assert_assignment_verdict(
            assignment,
            status="EXCEPTION_FLAGGED",
            qualification_basis="NONE",
            exception_code="DEGREE_LEVEL_INSUFFICIENT",
            alignment_score=1.0000,
        )

    def test_coursework_arm_qualifies_on_eighteen_aligned_hours(self, api, env):
        """PRD §3.4: "Under `COURSEWORK_18` the same evidence qualifies with
        `qualification_basis` `COURSEWORK_18_HOUR` and no exception code."

        Design: Difficulty/dual_variant_calc/qualification_policy_degree_field_vs_coursework_18_diverge_on_identical_dossier
        """
        state = _dual_policy_state(env)
        sec_cw = state["sec_cw"]

        response = api.create_course_assignment(
            assignment_payload(sec_cw["id"], state["faculty_id"], sec_cw["version"]),
            make_program_dean_headers(env.prog_cw_id),
        )
        assignment = validate_success(response, 201)

        assert_assignment_verdict(
            assignment,
            status="VERIFIED_QUALIFIED",
            qualification_basis="COURSEWORK_18_HOUR",
            exception_code=None,
            alignment_score=1.0000,
        )

    def test_both_arms_share_one_alignment_score_and_one_load_ledger(self, api, env):
        """PRD §3.4: "In both cases `alignment_score` is 1.0000, because the
        coursework record matches the section discipline exactly — and that is
        precisely why the `DEGREE_FIELD` arm reports `DEGREE_LEVEL_INSUFFICIENT`
        rather than `DISCIPLINE_MISALIGNED`."

        Design: Difficulty/dual_variant_calc/qualification_policy_degree_field_vs_coursework_18_diverge_on_identical_dossier
        """
        state = _dual_policy_state(env)
        faculty_id = state["faculty_id"]
        sec_df, sec_cw = state["sec_df"], state["sec_cw"]

        flagged = validate_success(
            api.create_course_assignment(
                assignment_payload(sec_df["id"], faculty_id, sec_df["version"]),
                make_program_dean_headers(env.prog_df_id),
            ),
            201,
        )
        qualified = validate_success(
            api.create_course_assignment(
                assignment_payload(sec_cw["id"], faculty_id, sec_cw["version"]),
                make_program_dean_headers(env.prog_cw_id),
            ),
            201,
        )

        assert flagged["alignment_score"] == qualified["alignment_score"], (
            "the same evidence set must yield the same alignment_score under both "
            "policies"
        )
        faculty = read_faculty(faculty_id)
        assert faculty["assigned_credit_hours"] == 6, (
            "both three-credit sections must land in the teaching-load ledger, "
            f"got {faculty['assigned_credit_hours']}"
        )
        assert_fields(
            read_section(sec_df["id"]), instructor_of_record_id=faculty_id
        )
