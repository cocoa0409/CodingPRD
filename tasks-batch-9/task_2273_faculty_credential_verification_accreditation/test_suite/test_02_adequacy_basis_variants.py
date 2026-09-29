"""Headcount adequacy and credit-hour-coverage adequacy over one roster."""

from test_helpers import (
    assert_fields,
    assert_ordered_codes,
    assert_program_adequacy,
    assert_roster_snapshot,
    assert_score,
    make_assignment,
    make_credentialed_faculty,
    make_generated_roster,
    make_section,
    make_verified_credential,
    read_assignment,
    read_program,
    read_roster,
    validate_success,
)


def _mixed_basis_state(env):
    """One terminal-degree instructor on a 1-credit lab, one coursework-qualified
    instructor on a 4-credit survey, both inside the coursework program."""
    morgan = make_credentialed_faculty(
        "Morgan Ellis",
        "morgan.ellis@example.edu",
        "FULL_TIME",
        env.prog_cw_id,
        "MASTERS",
        env.journ_id,
        "Northern University",
        graduate_credit_hours_in_discipline=36,
    )["faculty"]
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
    sec_lab = make_section(
        env.prog_cw_id,
        env.term_id,
        env.journ_id,
        "JOUR190",
        "Newsroom Lab",
        credit_hours=1,
        meeting_days=["WED"],
        meeting_start_minute=540,
        meeting_end_minute=600,
    )
    sec_survey = make_section(
        env.prog_cw_id,
        env.term_id,
        env.journ_id,
        "JOUR110",
        "Media Survey",
        credit_hours=4,
        meeting_days=["THU"],
        meeting_start_minute=540,
        meeting_end_minute=660,
    )
    asn_lab = make_assignment(sec_lab["id"], morgan["id"], env.prog_cw_id)
    asn_survey = make_assignment(sec_survey["id"], dana["id"], env.prog_cw_id)
    roster = make_generated_roster(env.prog_cw_id, env.term_id)
    return {
        "morgan_id": morgan["id"],
        "dana_id": dana["id"],
        "asn_lab": asn_lab,
        "asn_survey": asn_survey,
        "roster": roster,
    }


class TestAdequacyBasisDivergence:
    def test_credit_hour_coverage_basis_weights_the_four_credit_section(self, api, env):
        """PRD §3.6: "Under `CREDIT_HOUR_COVERAGE`, the denominator is the sum of
        `CourseSection.credit_hours` over the included set and the numerator is
        that same sum over the terminal subset."

        Design: Difficulty/dual_variant_calc/adequacy_basis_headcount_vs_credit_hour_coverage_cross_status_bands
        """
        state = _mixed_basis_state(env)

        adequacy = validate_success(
            api.get_program_adequacy(
                env.prog_cw_id, env.dean_cw, {"term_id": env.term_id}
            )
        )

        assert_fields(
            adequacy,
            basis_applied="CREDIT_HOUR_COVERAGE",
            numerator=1,
            denominator=5,
            adequacy_status="INSUFFICIENT",
            unqualified_assignment_count=0,
            roster_id=state["roster"]["id"],
        )
        assert_score(adequacy["adequacy_ratio"], 0.2000, "adequacy_ratio")

    def test_headcount_override_recomputes_without_persisting(self, api, env):
        """PRD §3.6: "Under `HEADCOUNT`, the denominator is the count of distinct
        `faculty_member_id` values over the included set and the numerator is the
        count of distinct `faculty_member_id` values over the terminal subset."

        Design: Difficulty/dual_variant_calc/adequacy_basis_headcount_vs_credit_hour_coverage_cross_status_bands
        """
        _mixed_basis_state(env)

        overridden = validate_success(
            api.get_program_adequacy(
                env.prog_cw_id,
                env.dean_cw,
                {"term_id": env.term_id, "basis_override": "HEADCOUNT"},
            )
        )

        assert_fields(
            overridden, basis_applied="HEADCOUNT", numerator=1, denominator=2
        )
        assert_score(overridden["adequacy_ratio"], 0.5000, "adequacy_ratio")
        assert overridden["adequacy_status"] == "AT_RISK", (
            "0.5000 sits inside the 0.15 band below a 0.60 minimum, so the "
            f"override must report AT_RISK, got {overridden['adequacy_status']}"
        )

        program = read_program(env.prog_cw_id)
        assert_program_adequacy(
            program,
            adequacy_ratio=0.2000,
            adequacy_status="INSUFFICIENT",
            adequacy_term_id=env.term_id,
        )

    def test_roster_snapshot_counts_terminal_degree_only(self, api, env):
        """PRD §3.6: "`credit_hours_terminal_qualified` is that same sum
        restricted to included assignments whose `status` is `VERIFIED_QUALIFIED`
        and whose `qualification_basis` is `TERMINAL_DEGREE`."

        Design: Difficulty/dual_variant_calc/adequacy_basis_headcount_vs_credit_hour_coverage_cross_status_bands
        """
        state = _mixed_basis_state(env)

        roster = read_roster(state["roster"]["id"])

        assert_roster_snapshot(
            roster,
            total_assignment_count=2,
            distinct_faculty_count=2,
            flagged_exception_count=0,
            terminal_qualified_headcount=1,
            credit_hours_total=5,
            credit_hours_terminal_qualified=1,
            adequacy_ratio_snapshot=0.2000,
            certification_readiness="BLOCKED",
        )
        assert_ordered_codes(
            roster["blocking_reason_codes"],
            ["ADEQUACY_BELOW_MINIMUM"],
            "blocking_reason_codes",
        )
        assert read_assignment(state["asn_lab"]["id"])["qualification_basis"] == (
            "TERMINAL_DEGREE"
        ), "the aligned master's degree must qualify on TERMINAL_DEGREE"
        assert read_assignment(state["asn_survey"]["id"])["qualification_basis"] == (
            "COURSEWORK_18_HOUR"
        ), "the eighteen aligned graduate hours must qualify on COURSEWORK_18_HOUR"
