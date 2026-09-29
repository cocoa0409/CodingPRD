"""Writes gated on state that lives on a different entity entirely."""

from test_helpers import (
    advance_transcript,
    ApiErrorId,
    assert_assignment_verdict,
    assert_fields,
    assert_score,
    assignment_payload,
    file_credential,
    issue_findings,
    make_assignment,
    make_credentialed_faculty,
    make_faculty,
    make_generated_roster,
    make_program_dean_headers,
    make_section,
    make_started_review,
    read_faculty,
    read_program,
    read_roster,
    read_section,
    review_status_payload,
    set_clock,
    total_count,
    validate_error,
    validate_success,
    verification_payload,
    withdrawal_payload,
    withdraw_assignment,
    TEST_USERS,
)


def _prospect_state(env):
    """Noor Haddad: official transcript on file, verification still pending."""
    noor = make_faculty(
        "Noor Haddad", "noor.haddad@example.edu", "CLINICAL", env.prog_df_id
    )
    record = file_credential(
        noor["id"],
        "MASTERS",
        env.journ_id,
        "Northern University",
        is_foreign_institution=False,
        graduate_credit_hours_in_discipline=36,
    )
    advance_transcript(record["id"], "OFFICIAL_RECEIVED")
    section = make_section(
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
    return {
        "faculty_id": noor["id"],
        "record_id": record["id"],
        "section": section,
    }


def _attempt_assignment(api, env, state, expected_version):
    return api.create_course_assignment(
        assignment_payload(
            state["section"]["id"], state["faculty_id"], expected_version
        ),
        make_program_dean_headers(env.prog_df_id),
    )


class TestAssignmentGatedOnAppointmentStatus:
    def test_a_prospect_cannot_be_put_in_front_of_students(self, api, env):
        """PRD §3.4: "The faculty member must not be `SEPARATED`
        (`ERR_FACULTY_SEPARATED`) and must be `CREDENTIALED_ELIGIBLE` or
        `CONTRACTED` (`ERR_FACULTY_NOT_APPOINTABLE`) — a `PROSPECT` who has never
        been credentialed at all cannot be put in front of students".

        Design: Difficulty/cross_entity_state_dependency/assignment_creation_gated_on_faculty_appointment_status
        """
        state = _prospect_state(env)
        assert_fields(
            read_faculty(state["faculty_id"]),
            dossier_status="UNDER_REVIEW",
            appointment_status="PROSPECT",
        )

        response = _attempt_assignment(
            api, env, state, state["section"]["version"]
        )

        validate_error(response, ApiErrorId.ERR_FACULTY_NOT_APPOINTABLE)
        assert total_count(
            api.list_section_assignments(state["section"]["id"], env.dean_df)
        ) == 0, "the gated request must not have created an assignment row"
        assert (
            read_section(state["section"]["id"])["version"]
            == state["section"]["version"]
        ), "a rejected assignment write may not bump the section's version"

    def test_verification_flips_the_gate_open(self, api, env):
        """PRD §3.2: "Finally, if the dossier came out `VERIFIED` and
        `appointment_status` is still `PROSPECT`, the appointment is promoted to
        `CREDENTIALED_ELIGIBLE` in the same request."

        Design: Difficulty/cross_entity_state_dependency/assignment_creation_gated_on_faculty_appointment_status
        """
        state = _prospect_state(env)
        validate_error(
            _attempt_assignment(api, env, state, state["section"]["version"]),
            ApiErrorId.ERR_FACULTY_NOT_APPOINTABLE,
        )

        validate_success(
            api.decide_verification(
                state["record_id"],
                verification_payload("VERIFY"),
                TEST_USERS["analyst"],
            )
        )

        assert_fields(
            read_faculty(state["faculty_id"]),
            dossier_status="VERIFIED",
            appointment_status="CREDENTIALED_ELIGIBLE",
        )

    def test_the_identical_request_is_accepted_once_the_gate_opens(self, api, env):
        """PRD §2.10: "The referenced faculty member's `appointment_status` is
        `CREDENTIALED_ELIGIBLE` or `CONTRACTED` → otherwise
        `ERR_FACULTY_NOT_APPOINTABLE` (409). Applies to assignment creation only."

        Design: Difficulty/cross_entity_state_dependency/assignment_creation_gated_on_faculty_appointment_status
        """
        state = _prospect_state(env)
        original_version = state["section"]["version"]
        validate_error(
            _attempt_assignment(api, env, state, original_version),
            ApiErrorId.ERR_FACULTY_NOT_APPOINTABLE,
        )
        validate_success(
            api.decide_verification(
                state["record_id"],
                verification_payload("VERIFY"),
                TEST_USERS["analyst"],
            )
        )

        assignment = validate_success(
            _attempt_assignment(api, env, state, original_version), 201
        )

        assert_assignment_verdict(
            assignment,
            status="VERIFIED_QUALIFIED",
            qualification_basis="TERMINAL_DEGREE",
            exception_code=None,
            alignment_score=1.0000,
        )
        assert read_faculty(state["faculty_id"])["assigned_credit_hours"] == 3, (
            "the CLINICAL cap is 12 credit hours, so the load rule was never in play"
        )


def _findings_issued_state(env):
    """A clean review over a program that still carries one flagged assignment."""
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
    alex = make_credentialed_faculty(
        "Alex Stone",
        "alex.stone@example.edu",
        "ADJUNCT",
        env.prog_cw_id,
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
    asn_ok = make_assignment(sec_a["id"], morgan["id"], env.prog_df_id)
    asn_bad = make_assignment(sec_b["id"], alex["id"], env.prog_df_id)
    roster = make_generated_roster(env.prog_df_id, env.term_id)
    review = make_started_review(env.prog_df_id, "COMPREHENSIVE")
    issue_findings(
        review["id"], 0, narrative="No findings recorded at the exit interview"
    )
    return {
        "morgan_id": morgan["id"],
        "alex_id": alex["id"],
        "asn_ok_id": asn_ok["id"],
        "asn_bad_id": asn_bad["id"],
        "roster_id": roster["id"],
        "review_id": review["id"],
    }


class TestReviewClosureGatedOnProgramAdequacy:
    def test_closure_is_refused_while_the_program_is_at_risk(self, api, env):
        """PRD §3.9: "A clean review in `FINDINGS_ISSUED` also closes directly with
        `FINDINGS_ISSUED → CLOSED_ACCEPTED`, under the same program-cleanliness
        requirement."

        Design: Difficulty/cross_entity_state_dependency/review_closure_gated_on_program_adequacy_posture
        """
        state = _findings_issued_state(env)
        program = read_program(env.prog_df_id)
        assert_score(program["adequacy_ratio"], 0.5000, "adequacy_ratio")
        assert_fields(
            program, adequacy_status="AT_RISK", unqualified_assignment_count=1
        )

        response = api.set_review_status(
            state["review_id"], review_status_payload("CLOSED_ACCEPTED"), TEST_USERS["reviewer"]
        )

        validate_error(response, ApiErrorId.ERR_PROGRAM_ADEQUACY_INSUFFICIENT)
        assert_fields(
            validate_success(
                api.get_review(state["review_id"], TEST_USERS["reviewer"])
            ),
            status="FINDINGS_ISSUED",
        )

    def test_the_evidence_freeze_blocks_the_repair_inside_the_window(self, api, env):
        """PRD §3.9: "while the clock date lies inside the review's fully closed
        window and the review sits in `IN_PROGRESS`, `FINDINGS_ISSUED` or
        `REMEDIATION_REQUIRED`, the program cannot take new course assignments,
        cannot withdraw existing ones".

        Design: Difficulty/cross_entity_state_dependency/review_closure_gated_on_program_adequacy_posture
        """
        state = _findings_issued_state(env)

        response = api.withdraw_assignment(
            state["asn_bad_id"],
            withdrawal_payload(reason="Reassigned to a qualified instructor of record"),
            make_program_dean_headers(env.prog_df_id),
        )

        validate_error(response, ApiErrorId.ERR_ACCREDITOR_REVIEW_LOCKOUT)
        assert_fields(
            read_program(env.prog_df_id), unqualified_assignment_count=1
        )

    def test_mutating_a_third_entity_opens_the_gate(self, api, env):
        """PRD §3.9: "Accepting, `RESPONSE_SUBMITTED → CLOSED_ACCEPTED`, requires
        the program to be clean — `adequacy_status` `ADEQUATE` and
        `unqualified_assignment_count` 0 — or it is rejected with
        `ERR_PROGRAM_ADEQUACY_INSUFFICIENT`."

        Design: Difficulty/cross_entity_state_dependency/review_closure_gated_on_program_adequacy_posture
        """
        state = _findings_issued_state(env)
        validate_error(
            api.set_review_status(
                state["review_id"],
                review_status_payload("CLOSED_ACCEPTED"),
                TEST_USERS["reviewer"],
            ),
            ApiErrorId.ERR_PROGRAM_ADEQUACY_INSUFFICIENT,
        )
        set_clock("2026-08-15T00:00:00Z")

        withdrawn = withdraw_assignment(
            state["asn_bad_id"],
            env.prog_df_id,
            reason="Reassigned to a qualified instructor of record",
        )

        assert_fields(withdrawn, status="WITHDRAWN")
        assert read_faculty(state["alex_id"])["assigned_credit_hours"] == 0
        roster = read_roster(state["roster_id"])
        assert_fields(
            roster,
            total_assignment_count=1,
            flagged_exception_count=0,
            certification_readiness="READY",
        )
        assert_score(
            roster["adequacy_ratio_snapshot"], 1.0000, "adequacy_ratio_snapshot"
        )
        program = read_program(env.prog_df_id)
        assert_score(program["adequacy_ratio"], 1.0000, "adequacy_ratio")
        assert_fields(
            program, adequacy_status="ADEQUATE", unqualified_assignment_count=0
        )

        closed = validate_success(
            api.set_review_status(
                state["review_id"],
                review_status_payload("CLOSED_ACCEPTED"),
                TEST_USERS["reviewer"],
            )
        )
        assert_fields(closed, status="CLOSED_ACCEPTED")
