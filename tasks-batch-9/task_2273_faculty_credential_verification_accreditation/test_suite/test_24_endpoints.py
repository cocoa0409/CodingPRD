"""Endpoint behaviour: computed reads, the launch loop and partial updates."""

from test_helpers import (
    ApiErrorId,
    assert_assignment_verdict,
    assert_fields,
    assert_hours,
    assert_program_adequacy,
    assert_roster_snapshot,
    assert_score,
    assert_total_count,
    assert_version_advanced_by,
    assignment_payload,
    generate_roster,
    ids_of,
    justification_decision_payload,
    launch_decision_payload,
    make_assignment,
    make_credentialed_faculty,
    make_generated_roster,
    make_pd_record,
    make_reviewed_justification,
    make_section,
    read_assignment,
    read_faculty,
    read_program,
    read_roster,
    read_section,
    set_pd_status,
    submit_launch_review,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)


class TestEmptyRosterAdequacyRead:
    def test_a_zero_denominator_reads_as_zero_rather_than_failing(self, api, env):
        """PRD §3.6: "The ratio is the numerator divided by the denominator, carried
        to 4 decimal places and rounded half up, and it is 0.0000 whenever the
        denominator is 0 — division never errors."

        Design: Corner/endpoints/adequacy_read_on_an_empty_roster_returns_zero_not_an_error
        """
        roster = make_generated_roster(env.prog_df_id, env.term_id)

        read = validate_success(
            api.get_program_adequacy(
                env.prog_df_id, env.dean_df, {"term_id": env.term_id}
            )
        )

        assert_fields(
            read,
            numerator=0,
            denominator=0,
            adequacy_status="INSUFFICIENT",
            unqualified_assignment_count=0,
            roster_id=roster["id"],
            basis_applied="HEADCOUNT",
            program_id=env.prog_df_id,
            term_id=env.term_id,
        )
        assert_score(read["adequacy_ratio"], 0.0000, "adequacy_ratio")
        assert_roster_snapshot(
            read_roster(roster["id"]),
            total_assignment_count=0,
            distinct_faculty_count=0,
            credit_hours_total=0,
            generation_epoch=1,
            certification_readiness="BLOCKED",
            blocking_reason_codes=["ADEQUACY_BELOW_MINIMUM"],
        )


def _rejected_justification(env):
    """A thin justification rejected by the analyst who verified nothing."""
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
    assignment = make_assignment(tuesday["id"], alex["id"], env.prog_df_id)
    justification = make_reviewed_justification(
        assignment["id"],
        env.prog_df_id,
        documented_years_experience=2,
        industry_certification_level="NONE",
        alternative_credential_codes=["OSHA-30"],
        supervisor_attestation_on_file=True,
    )
    return {"assignment": assignment, "justification": justification}


class TestJustificationRevision:
    def test_reopening_a_rejection_erases_the_decision_trail(self, api, env):
        """PRD §3.5: "Resubmission is not the route back: the dean re-opens it instead
        through a revision capability that moves `REJECTED → DRAFT` and resets both
        `decided_by_user_id` and `decision_rationale` to null, incrementing the
        `version` by 1."

        Design: Corner/endpoints/revision_endpoint_clears_the_decision_trail_and_reopens_the_draft
        """
        state = _rejected_justification(env)
        rationale = "Two years is below the documented minimum"
        rejected = validate_success(
            api.decide_justification(
                state["justification"]["id"],
                justification_decision_payload("REJECT", decision_rationale=rationale),
                TEST_USERS["analyst_2"],
            )
        )
        assert_score(
            rejected["tested_experience_score"], 0.1750, "tested_experience_score"
        )
        assert_fields(
            rejected,
            status="REJECTED",
            decided_by_user_id="analyst-02",
            decision_rationale=rationale,
        )

        reopened = validate_success(
            api.revise_justification(
                state["justification"]["id"], {}, env.dean_df
            )
        )

        assert_fields(
            reopened,
            status="DRAFT",
            decided_by_user_id=None,
            decision_rationale=None,
        )
        assert_score(
            reopened["tested_experience_score"],
            0.1750,
            "tested_experience_score after the revision",
        )
        assert_version_advanced_by(reopened, rejected["version"], 1)
        assert_assignment_verdict(
            read_assignment(state["assignment"]["id"]),
            status="EXCEPTION_FLAGGED",
            qualification_basis="NONE",
            exception_code="DISCIPLINE_MISALIGNED",
        )


def _launch_candidates(env):
    """A flagged instructor of record and a qualified replacement in the wings."""
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
    flagged = make_assignment(tuesday["id"], alex["id"], env.prog_df_id)
    roster = make_generated_roster(env.prog_df_id, env.term_id)
    return {
        "morgan_id": morgan["id"],
        "section": tuesday,
        "flagged": flagged,
        "roster": roster,
    }


class TestLaunchGateRevisionLoop:
    def test_denial_then_remediation_reopens_the_gate_for_the_same_approval(
        self, api, env
    ):
        """PRD §3.1: "The launch gate is a small branching lifecycle on
        `launch_status`. A `ProgramDean` submitting their own program for
        faculty-adequacy review supplies a `term_id`, moving the program `PLANNING →
        ADEQUACY_REVIEW`; the same submission also drives the revision loop
        `ADEQUACY_DENIED → ADEQUACY_REVIEW` after a denied program has remediated."

        Design: Corner/endpoints/program_launch_is_gated_then_denied_then_approved_after_remediation
        """
        state = _launch_candidates(env)

        first_review = submit_launch_review(env.prog_df_id, env.term_id)
        assert_program_adequacy(
            first_review,
            launch_status="ADEQUACY_REVIEW",
            adequacy_status="INSUFFICIENT",
            adequacy_term_id=env.term_id,
            adequacy_ratio=0.0000,
        )

        validate_error(
            api.decide_launch(
                env.prog_df_id,
                launch_decision_payload("APPROVE", rationale="Requesting launch approval"),
                TEST_USERS["liaison"],
            ),
            ApiErrorId.ERR_PROGRAM_ADEQUACY_INSUFFICIENT,
        )
        assert_fields(read_program(env.prog_df_id), launch_status="ADEQUACY_REVIEW")

        denied = validate_success(
            api.decide_launch(
                env.prog_df_id,
                launch_decision_payload(
                    "DENY", rationale="One unqualified instructor of record"
                ),
                TEST_USERS["liaison"],
            )
        )
        assert_fields(denied, launch_status="ADEQUACY_DENIED")

        replacement = make_assignment(
            state["section"]["id"],
            state["morgan_id"],
            env.prog_df_id,
            expected_section_version=read_section(state["section"]["id"])["version"],
        )
        regenerated = generate_roster(state["roster"]["id"])
        second_review = submit_launch_review(env.prog_df_id, env.term_id)
        approved = validate_success(
            api.decide_launch(
                env.prog_df_id,
                launch_decision_payload(
                    "APPROVE",
                    rationale=(
                        "Roster remediated; all instructors of record hold terminal "
                        "degrees"
                    ),
                ),
                TEST_USERS["liaison"],
            )
        )

        assert_assignment_verdict(
            replacement,
            status="VERIFIED_QUALIFIED",
            qualification_basis="TERMINAL_DEGREE",
            exception_code=None,
        )
        assert_fields(
            read_assignment(state["flagged"]["id"]),
            status="SUPERSEDED",
            superseded_by_assignment_id=replacement["id"],
        )
        assert_roster_snapshot(
            regenerated,
            generation_epoch=2,
            adequacy_ratio_snapshot=1.0000,
            certification_readiness="READY",
            blocking_reason_codes=[],
        )
        assert_program_adequacy(
            second_review,
            launch_status="ADEQUACY_REVIEW",
            adequacy_status="ADEQUATE",
            adequacy_ratio=1.0000,
        )
        assert_fields(
            approved, launch_status="APPROVED_TO_LAUNCH", unqualified_assignment_count=0
        )


class TestAssignmentCrossReferences:
    def test_one_write_is_visible_from_the_section_and_the_faculty_side(self, api, env):
        """PRD §3.4: "The section's `version` increments by 1 as the concurrency
        parent, as do the faculty member's, any superseded assignment's, and the
        covering roster's and owning program's where they were touched."

        Design: Corner/endpoints/assignment_creation_links_section_and_faculty_from_both_directions
        """
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
        assert_fields(monday, instructor_of_record_id=None)

        assignment = validate_success(
            api.create_course_assignment(
                assignment_payload(monday["id"], morgan["id"], monday["version"]),
                env.dean_df,
            ),
            201,
        )

        nested_rows, nested_meta = validate_paginated(
            api.list_section_assignments(
                monday["id"], TEST_USERS["liaison"], {"limit": 10, "offset": 0}
            )
        )
        assert_total_count(nested_meta, 1, "the section's nested assignment listing")
        assert ids_of(nested_rows) == [assignment["id"]]
        assert_fields(nested_rows[0], course_section_id=monday["id"])

        flat_rows, flat_meta = validate_paginated(
            api.list_course_assignments(
                TEST_USERS["liaison"],
                {
                    "faculty_member_id": morgan["id"],
                    "status": "VERIFIED_QUALIFIED",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert_total_count(flat_meta, 1, "the faculty-filtered assignment listing")
        assert ids_of(flat_rows) == [assignment["id"]]

        assert_fields(
            read_section(monday["id"]), instructor_of_record_id=morgan["id"]
        )
        assert_version_advanced_by(read_section(monday["id"]), monday["version"], 1)
        refreshed = read_faculty(morgan["id"])
        assert_fields(refreshed, assigned_credit_hours=3)
        assert_version_advanced_by(refreshed, morgan["version"], 1)


class TestFacultyPartialUpdate:
    def test_a_class_change_leaves_identity_alone_and_re_runs_compliance(
        self, api, env
    ):
        """PRD §3.8: "`pd_compliant` is then true when `pd_hours_current_cycle`
        reaches the requirement for the faculty member's `employment_class`: 40 hours
        for `FULL_TIME`, 30 for `CLINICAL`, 20 for `ADJUNCT` and 10 for
        `GRADUATE_ASSISTANT`."

        Design: Corner/endpoints/faculty_update_is_partial_and_re_runs_pd_compliance
        """
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
        in_discipline = make_pd_record(
            dana["id"], env.journ_id, "CONFERENCE", 12.0, "2026-07-01"
        )
        parent_discipline = make_pd_record(
            dana["id"], env.comm_id, "COURSEWORK", 8.0, "2026-06-01"
        )
        set_pd_status(in_discipline["id"], "VERIFIED")
        set_pd_status(parent_discipline["id"], "VERIFIED")
        before = read_faculty(dana["id"])
        assert_hours(before["pd_hours_current_cycle"], 20.0, "pd_hours_current_cycle")
        assert_fields(before, pd_compliant=True)

        updated = validate_success(
            api.update_faculty_member(
                dana["id"], {"employment_class": "FULL_TIME"}, TEST_USERS["registrar"]
            )
        )

        assert_fields(
            updated,
            employment_class="FULL_TIME",
            email="dana.reyes@example.edu",
            full_name="Dana Reyes",
            home_program_id=env.prog_df_id,
            pd_compliant=False,
        )
        assert_hours(updated["pd_hours_current_cycle"], 20.0, "pd_hours_current_cycle")
        assert_version_advanced_by(updated, before["version"], 1)
        assert_fields(
            validate_success(
                api.get_pd_record(parent_discipline["id"], TEST_USERS["registrar"])
            ),
            discipline_relevant=True,
        )
