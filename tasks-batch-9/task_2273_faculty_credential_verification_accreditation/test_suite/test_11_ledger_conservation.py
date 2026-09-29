"""Compensating paths: the teaching-load ledger and the evaluation budget ledger."""

from test_helpers import (
    assert_cents,
    assert_fields,
    assignment_payload,
    evaluation_completion_payload,
    evaluation_payload,
    evaluation_status_payload,
    file_credential,
    make_assignment,
    make_credentialed_faculty,
    make_faculty,
    make_program_dean_headers,
    make_section,
    make_verified_credential,
    read_assignment,
    read_faculty,
    read_program,
    read_section,
    validate_success,
    withdraw_assignment,
    TEST_USERS,
)


def _two_instructors_state(env):
    """Dana (flagged under DEGREE_FIELD) and Morgan (aligned master's), both idle."""
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
    return {"dana_id": dana["id"], "morgan_id": morgan["id"], "section": section}


def _hours(faculty_id):
    return read_faculty(faculty_id)["assigned_credit_hours"]


class TestTeachingLoadLedgerConservation:
    def test_a_flagged_assignment_still_occupies_the_seat(self, api, env):
        """PRD §2.12: "Note what stays in the ledger: an `EXCEPTION_FLAGGED` or
        `REMEDIATION_IN_PROGRESS` assignment still occupies the seat and still
        counts."

        Design: Difficulty/compensating_invariant/assigned_credit_hours_ledger_conserved_across_supersession_and_withdrawal
        """
        state = _two_instructors_state(env)
        assert _hours(state["dana_id"]) == 0, "the ledger starts empty"

        first = make_assignment(
            state["section"]["id"],
            state["dana_id"],
            env.prog_df_id,
            expected_section_version=state["section"]["version"],
        )

        assert_fields(first, status="EXCEPTION_FLAGGED")
        assert _hours(state["dana_id"]) == 3
        assert_fields(
            read_section(state["section"]["id"]),
            instructor_of_record_id=state["dana_id"],
        )
        assert_fields(read_program(env.prog_df_id), unqualified_assignment_count=1)

    def test_supersession_moves_the_hours_without_drift(self, api, env):
        """PRD §3.4: "gives back its hours: the superseded instructor's
        `assigned_credit_hours` decreases by exactly that section's
        `credit_hours`."

        Design: Difficulty/compensating_invariant/assigned_credit_hours_ledger_conserved_across_supersession_and_withdrawal
        """
        state = _two_instructors_state(env)
        first = make_assignment(
            state["section"]["id"],
            state["dana_id"],
            env.prog_df_id,
            expected_section_version=state["section"]["version"],
        )
        refreshed = read_section(state["section"]["id"])["version"]

        second = validate_success(
            api.create_course_assignment(
                assignment_payload(
                    state["section"]["id"], state["morgan_id"], refreshed
                ),
                make_program_dean_headers(env.prog_df_id),
            ),
            201,
        )

        assert_fields(
            read_assignment(first["id"]),
            status="SUPERSEDED",
            superseded_by_assignment_id=second["id"],
        )
        assert _hours(state["dana_id"]) == 0
        assert _hours(state["morgan_id"]) == 3
        assert _hours(state["dana_id"]) + _hours(state["morgan_id"]) == 3, (
            "the three credit hours moved between instructors with no drift"
        )
        assert_fields(second, status="VERIFIED_QUALIFIED")
        assert_fields(
            read_section(state["section"]["id"]),
            instructor_of_record_id=state["morgan_id"],
        )
        assert_fields(read_program(env.prog_df_id), unqualified_assignment_count=0)

    def test_withdrawal_restores_the_pre_assignment_ledger(self, api, env):
        """PRD §3.4: "Withdrawal is the compensating path for the load ledger —
        `assigned_credit_hours` decreases by exactly the section's `credit_hours`,
        restoring the pre-creation value — and the section's
        `instructor_of_record_id` resets to null when this row held it."

        Design: Difficulty/compensating_invariant/assigned_credit_hours_ledger_conserved_across_supersession_and_withdrawal
        """
        state = _two_instructors_state(env)
        first = make_assignment(
            state["section"]["id"],
            state["dana_id"],
            env.prog_df_id,
            expected_section_version=state["section"]["version"],
        )
        second = make_assignment(
            state["section"]["id"],
            state["morgan_id"],
            env.prog_df_id,
            expected_section_version=read_section(state["section"]["id"])["version"],
        )

        withdrawn = withdraw_assignment(
            second["id"], env.prog_df_id, reason="Section cancelled"
        )

        assert_fields(withdrawn, status="WITHDRAWN")
        assert _hours(state["morgan_id"]) == 0
        assert_fields(
            read_section(state["section"]["id"]), instructor_of_record_id=None
        )
        assert_fields(read_assignment(first["id"]), status="SUPERSEDED")
        assert _hours(state["dana_id"]) == 0, (
            "the superseded row stays superseded and is never resurrected by the "
            "withdrawal"
        )
        assert _hours(state["dana_id"]) + _hours(state["morgan_id"]) == 0, (
            "the ledger is back to exactly its value before the first assignment"
        )


EXPEDITED_FEE_CENTS = 22591


def _foreign_record_state(env):
    """Dana holds one foreign master's and carries no teaching load at all."""
    dana = make_faculty(
        "Dana Reyes", "dana.reyes@example.edu", "ADJUNCT", env.prog_df_id
    )
    record = file_credential(
        dana["id"],
        "MASTERS",
        env.journ_id,
        "Universidad Central",
        is_foreign_institution=True,
        graduate_credit_hours_in_discipline=24,
    )
    return {"faculty_id": dana["id"], "record_id": record["id"]}


def _order(api, env, state):
    return validate_success(
        api.create_credential_evaluation(
            evaluation_payload(
                state["record_id"],
                env.prog_df_id,
                evaluator_agency="WES",
                page_count=24,
                service_level="EXPEDITED",
            ),
            TEST_USERS["analyst"],
        ),
        201,
    )


class TestCredentialBudgetLedgerConservation:
    def test_ordering_reserves_the_frozen_fee(self, api, env):
        """PRD §3.3: "Ordering reserves that exact amount: the billed program's
        `budget_reserved_cents` increases by `fee_cents` and its `version`
        increments by 1."

        Design: Difficulty/compensating_invariant/credential_budget_ledger_conserved_across_void_and_completion
        """
        state = _foreign_record_state(env)

        evaluation = _order(api, env, state)

        assert_cents(evaluation["fee_cents"], EXPEDITED_FEE_CENTS, "fee_cents")
        program = read_program(env.prog_df_id)
        assert_cents(
            program["budget_reserved_cents"],
            EXPEDITED_FEE_CENTS,
            "budget_reserved_cents",
        )
        assert_cents(program["budget_spent_cents"], 0, "budget_spent_cents")

    def test_voiding_leaves_no_residue_behind(self, api, env):
        """PRD §3.3: "Voiding is the compensating path and leaves no residue: the
        billed program's `budget_reserved_cents` decreases by `fee_cents`, returning
        it to its exact pre-order value, and `budget_spent_cents` is untouched."

        Design: Difficulty/compensating_invariant/credential_budget_ledger_conserved_across_void_and_completion
        """
        state = _foreign_record_state(env)
        first = _order(api, env, state)

        voided = validate_success(
            api.set_evaluation_status(
                first["id"],
                evaluation_status_payload("VOIDED"),
                TEST_USERS["analyst"],
            )
        )

        assert_fields(voided, status="VOIDED")
        assert_cents(voided["fee_cents"], EXPEDITED_FEE_CENTS, "fee_cents")
        after_void = read_program(env.prog_df_id)
        assert_cents(after_void["budget_reserved_cents"], 0, "budget_reserved_cents")
        assert_cents(after_void["budget_spent_cents"], 0, "budget_spent_cents")

        _order(api, env, state)

        assert_cents(
            read_program(env.prog_df_id)["budget_reserved_cents"],
            EXPEDITED_FEE_CENTS,
            "budget_reserved_cents",
        )

    def test_completion_converts_the_reservation_into_allocated_spend(self, api, env):
        """PRD §3.3: "If no program is left with any weight, `allocation_shares` is a
        single entry naming the `billed_program_id`, a `weight_credit_hours` of 0 and
        a `share_cents` equal to the whole fee."

        Design: Difficulty/compensating_invariant/credential_budget_ledger_conserved_across_void_and_completion
        """
        state = _foreign_record_state(env)
        evaluation = _order(api, env, state)
        in_review = validate_success(
            api.set_evaluation_status(
                evaluation["id"],
                evaluation_status_payload("IN_REVIEW"),
                TEST_USERS["analyst"],
            )
        )
        assert_fields(in_review, status="IN_REVIEW")
        assert_cents(
            read_program(env.prog_df_id)["budget_reserved_cents"],
            EXPEDITED_FEE_CENTS,
            "budget_reserved_cents",
        )

        completed = validate_success(
            api.set_evaluation_status(
                evaluation["id"],
                evaluation_completion_payload("MASTERS", env.journ_id, "EQUIVALENT"),
                TEST_USERS["analyst"],
            )
        )

        program = read_program(env.prog_df_id)
        assert_cents(program["budget_reserved_cents"], 0, "budget_reserved_cents")
        assert_cents(
            program["budget_spent_cents"], EXPEDITED_FEE_CENTS, "budget_spent_cents"
        )
        shares = completed["allocation_shares"]
        assert len(shares) == 1, (
            "an unassigned faculty member leaves a single billed-program share, got "
            f"{shares}"
        )
        assert_fields(
            shares[0], program_id=env.prog_df_id, weight_credit_hours=0
        )
        assert_cents(shares[0]["share_cents"], EXPEDITED_FEE_CENTS, "share_cents")
        assert sum(share["share_cents"] for share in shares) == completed[
            "fee_cents"
        ], "the shares must re-sum to the frozen fee exactly"
