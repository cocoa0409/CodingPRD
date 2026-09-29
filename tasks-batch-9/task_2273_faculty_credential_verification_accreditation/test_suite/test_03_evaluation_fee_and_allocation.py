"""The frozen evaluation fee and the way a completed fee is split."""

import pytest

from test_helpers import (
    assert_cents,
    assert_fields,
    evaluation_completion_payload,
    evaluation_payload,
    evaluation_status_payload,
    file_credential,
    make_assignment,
    make_credentialed_faculty,
    make_program,
    make_section,
    read_program,
    TEST_USERS,
    validate_success,
)


def _foreign_record_state(env):
    """Dana Reyes with a single foreign Journalism master's on file."""
    faculty = make_credentialed_faculty(
        "Dana Reyes",
        "dana.reyes@example.edu",
        "ADJUNCT",
        env.prog_df_id,
        "MASTERS",
        env.pr_id,
        "State University",
        graduate_credit_hours_in_discipline=30,
    )["faculty"]
    record = file_credential(
        faculty["id"],
        "MASTERS",
        env.journ_id,
        "Universidad Central",
        is_foreign_institution=True,
        graduate_credit_hours_in_discipline=24,
    )
    return {"faculty_id": faculty["id"], "record_id": record["id"]}


def _order(api, record_id, program_id, page_count, service_level):
    return api.create_credential_evaluation(
        evaluation_payload(
            record_id,
            program_id,
            evaluator_agency="WES",
            page_count=page_count,
            service_level=service_level,
        ),
        TEST_USERS["analyst"],
    )


class TestEvaluationFee:
    @pytest.mark.parametrize(
        "page_count,service_level,expected_fee",
        [
            (24, "EXPEDITED", 22591),
            (24, "STANDARD", 15580),
            (12, "EXPEDITED", 19459),
            (13, "EXPEDITED", 19720),
            (4, "STANDARD", 15000),
            (600, "EXPEDITED", 95000),
        ],
    )
    def test_fee_walks_pages_multiplier_floor_and_cap(
        self, api, env, page_count, service_level, expected_fee
    ):
        """PRD §3.3: "The first 8 billable pages cost 240 cents each. The next 12
        billable pages cost 180 cents each. Every billable page beyond those
        first 20 costs 120 cents each."

        Design: Difficulty/combinatorial_formula/evaluation_fee_tiered_pages_times_expedite_multiplier_with_floor_and_cap
        """
        state = _foreign_record_state(env)

        evaluation = validate_success(
            _order(api, state["record_id"], env.prog_df_id, page_count, service_level),
            201,
        )

        assert_cents(evaluation["fee_cents"], expected_fee, "fee_cents")
        assert evaluation["status"] == "ORDERED", (
            f"a new evaluation lands ORDERED, got {evaluation['status']}"
        )

    def test_expedite_multiplier_applies_before_the_floor_and_the_cap(self, api, env):
        """PRD §3.3: "This is the only rounding step in the fee, and it happens
        **before** the floor and the cap."

        Design: Difficulty/combinatorial_formula/evaluation_fee_tiered_pages_times_expedite_multiplier_with_floor_and_cap
        """
        state = _foreign_record_state(env)
        record_id = state["record_id"]

        expedited = validate_success(
            _order(api, record_id, env.prog_df_id, 24, "EXPEDITED"), 201
        )
        standard = validate_success(
            _order(api, record_id, env.prog_df_id, 24, "STANDARD"), 201
        )
        twelve = validate_success(
            _order(api, record_id, env.prog_df_id, 12, "EXPEDITED"), 201
        )
        thirteen = validate_success(
            _order(api, record_id, env.prog_df_id, 13, "EXPEDITED"), 201
        )

        assert expedited["fee_cents"] - standard["fee_cents"] == 7011, (
            "the expedite multiplier must scale the whole subtotal, not the page "
            "charge alone"
        )
        assert thirteen["fee_cents"] - twelve["fee_cents"] == 261, (
            "one more page inside the 180-cent bracket must cost 180 cents scaled "
            "by 1.45 and rounded half up"
        )

    def test_every_order_reserves_its_own_frozen_fee(self, api, env):
        """PRD §3.3: "Ordering reserves that exact amount: the billed program's
        `budget_reserved_cents` increases by `fee_cents` and its `version`
        increments by 1."

        Design: Difficulty/combinatorial_formula/evaluation_fee_tiered_pages_times_expedite_multiplier_with_floor_and_cap
        """
        state = _foreign_record_state(env)
        record_id = state["record_id"]
        orders = [
            (24, "EXPEDITED"),
            (24, "STANDARD"),
            (12, "EXPEDITED"),
            (13, "EXPEDITED"),
            (4, "STANDARD"),
            (600, "EXPEDITED"),
        ]

        total = 0
        for page_count, service_level in orders:
            evaluation = validate_success(
                _order(api, record_id, env.prog_df_id, page_count, service_level), 201
            )
            total += evaluation["fee_cents"]

        program = read_program(env.prog_df_id)
        assert_cents(program["budget_reserved_cents"], total, "budget_reserved_cents")
        assert_cents(program["budget_reserved_cents"], 187350, "budget_reserved_cents")
        assert_cents(program["budget_spent_cents"], 0, "budget_spent_cents")


def _allocation_state(env):
    """Morgan Ellis teaching in three programs, with one foreign record pending
    evaluation billed to the degree-field program."""
    prog_c = make_program(
        "MA Strategic Communication",
        env.comm_id,
        degree_level="MASTERS",
        qualification_policy="DEGREE_FIELD",
        adequacy_basis="HEADCOUNT",
        min_terminal_ratio=0.75,
        credential_budget_cents=200000,
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
    foreign = file_credential(
        morgan["id"],
        "MASTERS",
        env.journ_id,
        "Universidad Central",
        is_foreign_institution=True,
        graduate_credit_hours_in_discipline=24,
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
    sec_c = make_section(
        prog_c["id"],
        env.term_id,
        env.journ_id,
        "COMM601",
        "Strategic Communication Seminar",
        course_level="GRADUATE",
        credit_hours=4,
        building_code="HALL-B",
        meeting_days=["WED"],
        meeting_start_minute=900,
        meeting_end_minute=1020,
    )
    make_assignment(sec_df["id"], morgan["id"], env.prog_df_id)
    make_assignment(sec_cw["id"], morgan["id"], env.prog_cw_id)
    make_assignment(sec_c["id"], morgan["id"], prog_c["id"])
    return {
        "prog_c_id": prog_c["id"],
        "faculty_id": morgan["id"],
        "record_id": foreign["id"],
    }


def _order_and_review(api, record_id, billed_program_id):
    evaluation = validate_success(
        api.create_credential_evaluation(
            evaluation_payload(
                record_id,
                billed_program_id,
                evaluator_agency="ECE",
                page_count=24,
                service_level="EXPEDITED",
            ),
            TEST_USERS["analyst"],
        ),
        201,
    )
    validate_success(
        api.set_evaluation_status(
            evaluation["id"],
            evaluation_status_payload("IN_REVIEW"),
            TEST_USERS["analyst"],
        )
    )
    return evaluation


class TestEvaluationCostAllocation:
    def test_shares_are_floored_then_the_residual_walks_weight_desc(self, api, env):
        """PRD §3.3: "The surviving programs are then ordered by
        `weight_credit_hours` descending, and where weights tie, by the program's
        `created_at` ascending; one cent is handed to the first program in that
        order, one to the second, and so on until the residual is exhausted,
        wrapping around the same order should the residual exceed the number of
        programs."

        Design: Difficulty/combinatorial_formula/evaluation_cost_allocation_floor_then_residual_by_weight_desc_then_created_at
        """
        state = _allocation_state(env)
        evaluation = _order_and_review(api, state["record_id"], env.prog_df_id)

        completed = validate_success(
            api.set_evaluation_status(
                evaluation["id"],
                evaluation_completion_payload("MASTERS", env.journ_id, "EQUIVALENT"),
                TEST_USERS["analyst"],
            )
        )

        assert_cents(completed["fee_cents"], 22591, "fee_cents")
        shares = completed["allocation_shares"]
        assert [share["program_id"] for share in shares] == [
            state["prog_c_id"],
            env.prog_df_id,
            env.prog_cw_id,
        ], (
            "shares are recorded in allocation order: weight 4 first, then the two "
            f"weight-3 programs by created_at, got {shares!r}"
        )
        by_program = {share["program_id"]: share for share in shares}
        assert_fields(
            by_program[state["prog_c_id"]], weight_credit_hours=4, share_cents=9037
        )
        assert_fields(
            by_program[env.prog_df_id], weight_credit_hours=3, share_cents=6777
        )
        assert_fields(
            by_program[env.prog_cw_id], weight_credit_hours=3, share_cents=6777
        )
        assert sum(share["share_cents"] for share in shares) == 22591, (
            "the floored shares total 22590, so the single residual cent must be "
            "handed out to make the shares re-sum to the frozen fee exactly"
        )

    def test_completion_releases_the_reservation_and_spends_each_share(self, api, env):
        """PRD §3.3: "The billed program's `budget_reserved_cents` decreases by
        `fee_cents`, releasing the reservation. The cost allocation described
        below runs, writing `allocation_shares` and increasing each receiving
        program's `budget_spent_cents` by its own `share_cents`."

        Design: Difficulty/combinatorial_formula/evaluation_cost_allocation_floor_then_residual_by_weight_desc_then_created_at
        """
        state = _allocation_state(env)
        evaluation = _order_and_review(api, state["record_id"], env.prog_df_id)

        validate_success(
            api.set_evaluation_status(
                evaluation["id"],
                evaluation_completion_payload("MASTERS", env.journ_id, "EQUIVALENT"),
                TEST_USERS["analyst"],
            )
        )

        billed = read_program(env.prog_df_id)
        assert_cents(billed["budget_reserved_cents"], 0, "budget_reserved_cents")
        assert_cents(billed["budget_spent_cents"], 6777, "budget_spent_cents")
        assert_cents(
            read_program(env.prog_cw_id)["budget_spent_cents"], 6777, "budget_spent_cents"
        )
        assert_cents(
            read_program(state["prog_c_id"])["budget_spent_cents"],
            9037,
            "budget_spent_cents",
        )

    def test_equivalent_verdict_rewrites_the_effective_credential(self, api, env):
        """PRD §3.3: "When the verdict is `EQUIVALENT`, the underlying credential
        record's `effective_degree_level` is rewritten to the agency's
        `equivalency_degree_level` and its `effective_discipline_id` to the
        agency's `equivalency_discipline_id` — for a domestic record, or a foreign
        record without a completed equivalent verdict, the effective level and
        discipline simply mirror the claimed `degree_level` and `discipline_id`."

        Design: Difficulty/combinatorial_formula/evaluation_cost_allocation_floor_then_residual_by_weight_desc_then_created_at
        """
        state = _allocation_state(env)
        evaluation = _order_and_review(api, state["record_id"], env.prog_df_id)

        validate_success(
            api.set_evaluation_status(
                evaluation["id"],
                evaluation_completion_payload("MASTERS", env.journ_id, "EQUIVALENT"),
                TEST_USERS["analyst"],
            )
        )

        record = validate_success(
            api.get_credential_record(state["record_id"], TEST_USERS["analyst"])
        )
        assert_fields(
            record,
            effective_degree_level="MASTERS",
            effective_discipline_id=env.journ_id,
        )
