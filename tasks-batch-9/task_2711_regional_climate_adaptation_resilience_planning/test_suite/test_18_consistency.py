"""Read-your-writes: every derived field is already in the response that wrote it.

PRD 4 states what a write hands back — "a create or mutate operation returns the
created or updated resource in the `data` field of the envelope described in §2.2"
— so each test compares that response against the very next read of the same rows,
with no recompute call and no intervening write.
"""

from test_helpers import (
    ADMIN,
    EQUITY,
    allocation_payload,
    api_client,
    assert_all_null,
    assert_fields,
    cast_endorsement,
    certified_levee_context,
    create_capital_program,
    create_harbor,
    create_plan_cycle,
    create_project,
    create_ridge,
    create_screened_project,
    open_endorsement_round,
    open_engagement,
    read_plan_cycle,
    read_project,
    read_tally,
    validate_success,
)

# PRD 3.5's five-step cost stack for the 42000000-cent PROTECT levee.
COST_STACK_FIELDS = (
    "escalated_cost_cents",
    "admin_rate_bps",
    "admin_fee_cents",
    "total_program_cost_cents",
    "grant_match_share_bps",
    "screen_score",
)
LEVEE_COST_STACK = {
    "escalated_cost_cents": 47040000,
    "admin_rate_bps": 900,
    "admin_fee_cents": 4233600,
    "total_program_cost_cents": 51273600,
    "grant_match_share_bps": 2500,
    "screen_score": 0.6925,
}


class TestTheScreenResponseCarriesTheWholeCostStack:
    """Nothing about the price is deferred to a later pass."""

    def test_the_write_response_and_the_next_read_agree_field_for_field(self):
        """Six derived fields are null, then written, then read back unchanged.

        PRD 3.5 lists what screening persists: "`escalated_cost_cents`,
        `admin_rate_bps`, `admin_fee_cents`, `total_program_cost_cents`,
        `grant_match_share_bps` and `screen_score` are all persisted on either branch",
        and PRD 3.5 fixes their pre-screen state: "`escalated_cost_cents`,
        `admin_rate_bps`, `admin_fee_cents`, `total_program_cost_cents`,
        `grant_match_share_bps`, `screen_score` ... are all null until the action that
        produces each of them runs."  The screen response must therefore already carry
        them, because PRD 4 says "a create or mutate operation returns the created or
        updated resource in the `data` field of the envelope described in §2.2".

        Design: Corner/consistency_model/screen_response_already_carries_the_whole_cost_stack_and_the_decision
        """
        harbor = create_harbor()
        cycle = create_plan_cycle()
        project = create_project(cycle["id"], harbor["id"])
        assert_all_null(project, COST_STACK_FIELDS, "the unscreened project")
        assert_fields(
            project, {"screening_status": "PROPOSED"}, "the unscreened project"
        )

        response = api_client.screen_project(project["id"], ADMIN())

        screened = validate_success(response, 200)
        expected = dict(LEVEE_COST_STACK)
        expected["screening_status"] = "SCREENED_IN"
        assert_fields(screened, expected, "the screen call's own response body")

        read_back = read_project(project["id"])

        assert_fields(read_back, expected, "the project on the very next read")
        assert {field: read_back[field] for field in COST_STACK_FIELDS} == {
            field: screened[field] for field in COST_STACK_FIELDS
        }, (
            "the write response and the later read must not disagree on any cost-stack "
            f"field, got {screened} then {read_back}"
        )


class TestTheAllocationResponseAndTheLedgerAgreeAtOnce:
    """Both sides of the cross-aggregate write land inside the same request."""

    def test_one_allocation_writes_the_project_and_the_program_together(self):
        """The response carries the priority score; the next read carries the ledger.

        PRD 3.7: "A successful allocation writes `capital_program_id` and
        `allocated_cents` onto the project, and computes its `priority_score` from three
        weighted components", and "The allocation then **recomputes the program ledger
        from scratch** rather than adjusting it by a delta ... Over that set,
        `committed_cents` is the sum of `allocated_cents`, and `available_cents` is
        `authorized_cents` minus `committed_cents`. `equity_committed_cents` is the sum of
        `allocated_cents` restricted to those projects whose `equity_benefit_share_bps` is
        at least the program's `equity_target_bps`."  Both sides are visible without a
        recompute call, because PRD 4 says "a create or mutate operation returns the
        created or updated resource in the `data` field of the envelope described in §2.2"
        and the ledger fields above are written by that same request.

        Design: Corner/consistency_model/allocation_response_and_the_program_ledger_agree_without_a_second_request
        """
        context = certified_levee_context()
        program = create_capital_program(authorized_cents=100000000)

        response = api_client.allocate(
            program["id"],
            allocation_payload(context["project"]["id"], 51273600, program["version"]),
            ADMIN(),
        )

        allocated = validate_success(response, 200)
        assert_fields(
            allocated,
            {
                "program_status": "PROGRAMMED",
                "allocated_cents": 51273600,
                "equity_benefit_share_bps": 10000,
                "priority_score": 0.6129,
                "capital_program_id": program["id"],
            },
            "the allocation call's own response body",
        )

        ledger = validate_success(api_client.get_capital_program(program["id"], EQUITY()))

        assert_fields(
            ledger,
            {
                "committed_cents": 51273600,
                "available_cents": 48726400,
                "equity_committed_cents": 51273600,
                "equity_achieved_bps": 10000,
                "funding_posture": "OPEN",
            },
            "the parent program on the very next read",
        )
        assert ledger["committed_cents"] + ledger["available_cents"] == ledger[
            "authorized_cents"
        ], (
            "committed_cents plus available_cents must still equal authorized_cents, got "
            f"{ledger['committed_cents']} + {ledger['available_cents']} != "
            f"{ledger['authorized_cents']}"
        )
        read_back = validate_success(
            api_client.get_project(context["project"]["id"], EQUITY())
        )
        assert_fields(
            read_back,
            {"priority_score": 0.6129, "allocated_cents": 51273600},
            "the funded project read by a second role",
        )


class TestTheTallyReflectsEveryVoteImmediately:
    """The projection recomputes on read, with no lag and no recompute call."""

    def test_two_casts_move_the_projection_from_short_to_adopted(self):
        """Three reads of the same projection, each separated only by one endorsement.

        PRD 3.8 defines the projection: "the system also exposes a **read-only
        projection** of it that writes nothing at all. It reports the cycle's current
        `round_number`, the `total_active_weight` denominator, the `supporting_weight` and
        `veto_weight` numerators, the resulting `achieved_weight_bps`, the cycle's
        configured `quorum_weight_bps`, and a `projected_outcome` string naming which of
        the three outcomes closing the round right now would produce."  The arithmetic it
        must already reflect is PRD 3.8's: "`achieved_weight_bps` is 0 when the
        denominator is 0, and otherwise ten thousand multiplied by the supporting weight
        divided by the denominator, floored to whole basis points", against outcome rule 2
        — "if `achieved_weight_bps` is at least the cycle's `quorum_weight_bps`, the
        outcome is **adopted**" — and rule 3, "Otherwise the outcome is **short**."

        Design: Corner/consistency_model/an_endorsement_is_inside_the_tally_on_the_very_next_read
        """
        harbor = create_harbor()
        ridge = create_ridge()
        cycle = create_plan_cycle(quorum_weight_bps=6600, required_session_count=0)
        create_screened_project(cycle["id"], harbor["id"])
        open_engagement(cycle["id"])
        open_endorsement_round(cycle["id"])

        before_any_vote = read_tally(cycle["id"])
        first_cast = cast_endorsement(cycle["id"], harbor["id"], decision="ENDORSED")
        after_one_vote = read_tally(cycle["id"])
        cast_endorsement(cycle["id"], ridge["id"], decision="ENDORSED")
        after_both_votes = read_tally(cycle["id"])

        assert_fields(
            before_any_vote,
            {"round_number": 1, "total_active_weight": 7, "supporting_weight": 0,
             "veto_weight": 0, "achieved_weight_bps": 0, "quorum_weight_bps": 6600},
            "the projection before any vote",
        )
        assert_fields(
            first_cast, {"weight_at_cast": 4}, "Harbor's endorsement"
        )
        assert_fields(
            after_one_vote,
            {"total_active_weight": 7, "supporting_weight": 4, "veto_weight": 0,
             "achieved_weight_bps": 5714},
            "the projection one instant after Harbor's cast",
        )
        assert_fields(
            after_both_votes,
            {"total_active_weight": 7, "supporting_weight": 7, "veto_weight": 0,
             "achieved_weight_bps": 10000},
            "the projection one instant after Ridge's cast",
        )
        assert isinstance(after_both_votes["projected_outcome"], str) and (
            after_both_votes["projected_outcome"]
        ), (
            "projected_outcome must be a non-empty string, got "
            f"{after_both_votes['projected_outcome']!r}"
        )
        assert after_both_votes["projected_outcome"] != before_any_vote[
            "projected_outcome"
        ], (
            "the projection must name a different outcome once the quorum is cleared, "
            f"but both reads said {before_any_vote['projected_outcome']!r}"
        )
        assert read_tally(cycle["id"])["round_number"] == 1, (
            "the projection writes nothing, so the round must not have advanced"
        )
        assert_fields(
            read_plan_cycle(cycle["id"]),
            {"status": "ENDORSEMENT_ROUND", "round_number": 1},
            "the cycle, which only closing the round may move",
        )
