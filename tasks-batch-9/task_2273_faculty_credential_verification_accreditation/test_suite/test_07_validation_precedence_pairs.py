"""Two validation-precedence pairs, each with the lower rung peeled away."""

from test_helpers import (
    ApiErrorId,
    assert_cents,
    assert_fields,
    assignment_payload,
    clock_payload,
    evaluation_payload,
    file_credential,
    make_assignment,
    make_credentialed_faculty,
    make_faculty,
    make_program,
    make_program_dean_headers,
    make_section,
    make_started_review,
    make_verified_credential,
    move_term,
    read_faculty,
    read_program,
    TEST_USERS,
    total_count,
    validate_error,
    validate_success,
)


def _overlapping_sections_state(env):
    """Two same-building Monday sections that overlap by twenty minutes."""
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
        "JOUR103",
        "Newsroom Ethics",
        credit_hours=3,
        meeting_days=["MON"],
        meeting_start_minute=600,
        meeting_end_minute=680,
    )
    first = make_assignment(sec_a["id"], dana["id"], env.prog_df_id)
    return {
        "faculty_id": dana["id"],
        "sec_a": sec_a,
        "sec_b": sec_b,
        "assignment_id": first["id"],
    }


class TestTermLockOutranksTeachingBlockConflict:
    def test_open_term_reports_only_the_teaching_block_conflict(self, api, env):
        """PRD §3.4: "A conflict is reported as `ERR_TEACHING_BLOCK_CONFLICT`, but
        only once the term-lock check has already passed."

        Design: Difficulty/priority_pair_validation_conflict/term_locked_state_outranks_teaching_block_business_constraint
        """
        state = _overlapping_sections_state(env)
        sec_b = state["sec_b"]

        response = api.create_course_assignment(
            assignment_payload(
                sec_b["id"],
                state["faculty_id"],
                sec_b["version"],
                assignment_role="CO_INSTRUCTOR",
            ),
            make_program_dean_headers(env.prog_df_id),
        )

        validate_error(response, ApiErrorId.ERR_TEACHING_BLOCK_CONFLICT)
        assert total_count(
            api.list_section_assignments(sec_b["id"], env.dean_df)
        ) == 0, "the rejected attempt must not have created an assignment row"

    def test_closed_term_reports_the_term_lock_instead(self, api, env):
        """PRD §2.10: "**This check outranks the teaching-block conflict check at
        rung 24** — a request that is both in a closed term and double-booked
        reports the term lock."

        Design: Difficulty/priority_pair_validation_conflict/term_locked_state_outranks_teaching_block_business_constraint
        """
        state = _overlapping_sections_state(env)
        sec_b = state["sec_b"]
        move_term(env.term_id, "ROSTER_LOCKED")
        closed = move_term(env.term_id, "CLOSED")
        assert_fields(closed, status="CLOSED")

        response = api.create_course_assignment(
            assignment_payload(
                sec_b["id"],
                state["faculty_id"],
                sec_b["version"],
                assignment_role="CO_INSTRUCTOR",
            ),
            make_program_dean_headers(env.prog_df_id),
        )

        validate_error(response, ApiErrorId.ERR_TERM_LOCKED)
        assert total_count(
            api.list_section_assignments(sec_b["id"], env.dean_df)
        ) == 0, "neither rejected attempt may leave an assignment row behind"
        assert read_faculty(state["faculty_id"])["assigned_credit_hours"] == 0, (
            "closing the term drops its hours out of the teaching-load ledger"
        )


def _tight_budget_state(env):
    """A pilot program with a 10,000-cent ceiling under an on-site review."""
    program = make_program(
        "BS Journalism (Pilot Budget)",
        env.journ_id,
        degree_level="BACHELORS",
        qualification_policy="DEGREE_FIELD",
        adequacy_basis="HEADCOUNT",
        min_terminal_ratio=0.75,
        is_substantive_change=True,
        credential_budget_cents=10000,
    )
    faculty = make_faculty(
        "Priya Raman", "priya.raman@example.edu", "ADJUNCT", program["id"]
    )
    record = file_credential(
        faculty["id"],
        "MASTERS",
        env.journ_id,
        "Universidad Central",
        is_foreign_institution=True,
        graduate_credit_hours_in_discipline=24,
    )
    review = make_started_review(program["id"], "SUBSTANTIVE_CHANGE")
    return {
        "program_id": program["id"],
        "record_id": record["id"],
        "review_id": review["id"],
    }


def _order_expedited(api, record_id, program_id):
    return api.create_credential_evaluation(
        evaluation_payload(
            record_id,
            program_id,
            evaluator_agency="WES",
            page_count=24,
            service_level="EXPEDITED",
        ),
        TEST_USERS["analyst"],
    )


class TestReviewLockoutOutranksBudgetCeiling:
    def test_order_inside_the_review_window_reports_the_lockout(self, api, env):
        """PRD §2.10: "**This check outranks the credential budget ceiling at rung
        35** — an over-budget order placed during a review window reports the
        lockout."

        Design: Difficulty/priority_pair_validation_conflict/accreditor_lockout_safety_outranks_credential_budget_fiscal
        """
        state = _tight_budget_state(env)

        response = _order_expedited(api, state["record_id"], state["program_id"])

        validate_error(response, ApiErrorId.ERR_ACCREDITOR_REVIEW_LOCKOUT)
        program = read_program(state["program_id"])
        assert_cents(program["budget_reserved_cents"], 0, "budget_reserved_cents")
        assert_cents(program["budget_spent_cents"], 0, "budget_spent_cents")

    def test_moving_the_clock_past_the_window_exposes_the_budget_ceiling(self, api, env):
        """PRD §3.3: "Ordering is also blocked while the billed program is under an
        on-site review window, with `ERR_ACCREDITOR_REVIEW_LOCKOUT`, and that
        lockout is reported ahead of any budget problem."

        Design: Difficulty/priority_pair_validation_conflict/accreditor_lockout_safety_outranks_credential_budget_fiscal
        """
        state = _tight_budget_state(env)
        validate_error(
            _order_expedited(api, state["record_id"], state["program_id"]),
            ApiErrorId.ERR_ACCREDITOR_REVIEW_LOCKOUT,
        )
        validate_success(
            api.set_clock(clock_payload("2026-08-15T00:00:00Z"), TEST_USERS["admin"])
        )

        response = _order_expedited(api, state["record_id"], state["program_id"])

        validate_error(response, ApiErrorId.ERR_CREDENTIAL_BUDGET_EXCEEDED)
        assert total_count(
            api.list_credential_evaluations(
                TEST_USERS["analyst"], {"billed_program_id": state["program_id"]}
            )
        ) == 0, "neither rejected order may leave an evaluation row behind"
        assert_fields(
            validate_success(
                api.get_review(state["review_id"], TEST_USERS["reviewer"])
            ),
            status="IN_PROGRESS",
        )
