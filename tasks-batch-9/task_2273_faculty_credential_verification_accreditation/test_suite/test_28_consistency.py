"""Read-your-write: the verdict, the snapshot and the adequacy all land together."""

from test_helpers import (
    assert_assignment_verdict,
    assert_fields,
    assert_ordered_codes,
    assert_program_adequacy,
    assert_roster_snapshot,
    assert_score,
    assignment_payload,
    make_assignment,
    make_credentialed_faculty,
    make_generated_roster,
    make_section,
    read_faculty,
    validate_success,
    TEST_USERS,
)


def _clean_roster_and_a_waiting_section(env):
    """A READY roster over one qualified instructor, plus an unassigned section."""
    morgan = make_credentialed_faculty(
        "Morgan Ellis",
        "morgan.ellis@example.edu",
        "FULL_TIME",
        env.prog_cw_id,
        "MASTERS",
        env.journ_id,
        "Lakeside University",
        graduate_credit_hours_in_discipline=36,
    )["faculty"]
    alex = make_credentialed_faculty(
        "Alex Stone",
        "alex.stone@example.edu",
        "ADJUNCT",
        env.prog_cw_id,
        "MASTERS",
        env.pr_id,
        "Harbor College",
        graduate_credit_hours_in_discipline=30,
    )["faculty"]
    monday = make_section(
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
    tuesday = make_section(
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
    make_assignment(monday["id"], morgan["id"], env.prog_df_id)
    roster = make_generated_roster(env.prog_df_id, env.term_id)
    return {"alex": alex, "waiting_section": tuesday, "roster": roster}


class TestImmediateConsistency:
    def test_the_write_response_and_the_next_reads_already_agree(self, api, env):
        """PRD §3.4: "Once the checks pass, the assignment is created and the
        qualification verdict is decided **immediately**, so the create response already
        carries a settled `status`, `qualification_basis`, `exception_code` and
        `alignment_score`."  PRD §1: "There is no eventual consistency and no background
        sweep."

        Design: Corner/consistency_model/computed_and_cascaded_fields_are_visible_in_the_same_response
        """
        state = _clean_roster_and_a_waiting_section(env)
        assert_roster_snapshot(
            state["roster"],
            generation_epoch=1,
            certification_readiness="READY",
            blocking_reason_codes=[],
            adequacy_ratio_snapshot=1.0000,
        )

        created = validate_success(
            api.create_course_assignment(
                assignment_payload(
                    state["waiting_section"]["id"],
                    state["alex"]["id"],
                    state["waiting_section"]["version"],
                ),
                env.dean_df,
            ),
            201,
        )

        assert_assignment_verdict(
            created,
            status="EXCEPTION_FLAGGED",
            qualification_basis="NONE",
            exception_code="DISCIPLINE_MISALIGNED",
            alignment_score=0.6500,
        )

        roster_read = validate_success(
            api.get_roster(state["roster"]["id"], TEST_USERS["liaison"])
        )
        program_read = validate_success(
            api.get_program(env.prog_df_id, TEST_USERS["liaison"])
        )

        assert_roster_snapshot(
            roster_read,
            total_assignment_count=2,
            distinct_faculty_count=2,
            flagged_exception_count=1,
            terminal_qualified_headcount=1,
            certification_readiness="BLOCKED",
        )
        assert_score(
            roster_read["adequacy_ratio_snapshot"],
            0.5000,
            "adequacy_ratio_snapshot on the first read after the write",
        )
        assert_ordered_codes(
            roster_read["blocking_reason_codes"],
            ["EXCEPTIONS_OUTSTANDING", "ADEQUACY_BELOW_MINIMUM"],
            "blocking_reason_codes in their declared append order",
        )
        assert roster_read["generation_epoch"] == 1, (
            "a cascade recompute is not a regeneration"
        )
        assert_program_adequacy(
            program_read,
            unqualified_assignment_count=1,
            adequacy_status="AT_RISK",
            adequacy_ratio=0.5000,
        )
        assert_fields(read_faculty(state["alex"]["id"]), assigned_credit_hours=3)
