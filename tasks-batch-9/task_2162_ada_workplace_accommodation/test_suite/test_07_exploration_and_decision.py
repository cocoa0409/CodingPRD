"""The interactive exploration loop and the decision that closes it."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_case,
    assert_calendar_date,
    assert_ledger_matches_options,
    assess_option,
    decide_case,
    propose_option,
    read_case,
    read_option,
    read_profile,
    set_clock,
    setup_case_at_decision_pending,
    setup_case_at_hardship_review,
    setup_case_at_option_exploration,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
FINANCE = TEST_USERS["finance_headers"]

TWO_DUTIES = ({"criticality_weight": 5}, {"criticality_weight": 5})
HOIST = {
    "one_time_cost_cents": 100_003,
    "recurring_monthly_cost_cents": 4_315,
    "implementation_days": 30,
}
UNDUE_SPEC = {
    "one_time_cost_cents": 121_995,
    "recurring_monthly_cost_cents": 0,
    "implementation_days": 60,
}


def _blocked_single_option_case(department_code):
    """A case whose only option was assessed UNDUE, so exploration must reopen."""
    ctx = setup_case_at_option_exploration(
        functions=TWO_DUTIES,
        department_code=department_code,
        department_annual_budget_cents=1_500_000,
        employer_annual_budget_cents=800_000_000,
    )
    propose_option(
        ctx, covers=[ctx["functions"][0]["id"]], option_code="OPT-ONLY", **HOIST
    )
    advance_case(ctx, "HARDSHIP_REVIEW")
    assess_option(ctx, ctx["options"][0], "SITE_LOCAL")
    return ctx


def test_the_case_returns_to_a_stage_it_already_left(api):
    """PRD §3.6: "When instead no option remains `PROPOSED` and
    `cleared_option_count` is zero — every proposal was ruled an undue hardship —
    the parties must keep talking: the coordinator advances the case back from
    `HARDSHIP_REVIEW` to `OPTION_EXPLORATION`, which increments
    `interactive_round_count` by one."
    PRD §3.5: "Exploration ends when the coordinator advances the case from
    `OPTION_EXPLORATION` to `HARDSHIP_REVIEW`, which requires at least one
    option on the case in `PROPOSED` or `CLEARED`."

    Design: Difficulty/non_linear_state_machine/case_cycles_hardship_review_back_to_option_exploration
    """
    set_clock()
    ctx = _blocked_single_option_case("OPS")
    assert read_case(ctx["case"]["id"])["stage"] == "HARDSHIP_REVIEW"

    reopened = advance_case(ctx, "OPTION_EXPLORATION")
    assert reopened["stage"] == "OPTION_EXPLORATION"
    assert reopened["interactive_round_count"] == 1

    propose_option(
        ctx,
        option_code="OPT-ROUND2",
        category="JOB_RESTRUCTURING",
        one_time_cost_cents=40_000,
        implementation_days=10,
    )
    back = advance_case(ctx, "HARDSHIP_REVIEW")

    assert back["stage"] == "HARDSHIP_REVIEW", (
        "the stage holds the same value it held before the loop began"
    )
    assert back["interactive_round_count"] == 1


def test_the_blocked_option_survives_the_exploration_loop_untouched(api):
    """PRD §3.6: "**Branch B — blocked.** A verdict of `UNDUE` moves the option
    `PROPOSED → HARDSHIP_BLOCKED`, increments the case's `blocked_option_count`
    by one, and increments the option's `version` by one."
    PRD §3.6: "When instead no option remains `PROPOSED` and
    `cleared_option_count` is zero — every proposal was ruled an undue hardship —
    the parties must keep talking: the coordinator advances the case back from
    `HARDSHIP_REVIEW` to `OPTION_EXPLORATION`, which increments
    `interactive_round_count` by one."

    Design: Difficulty/non_linear_state_machine/case_cycles_hardship_review_back_to_option_exploration
    """
    set_clock()
    ctx = _blocked_single_option_case("OP3")
    blocked = ctx["options"][0]

    advance_case(ctx, "OPTION_EXPLORATION")
    second = propose_option(
        ctx,
        option_code="OPT-ROUND2",
        category="JOB_RESTRUCTURING",
        one_time_cost_cents=40_000,
        implementation_days=10,
    )
    advance_case(ctx, "HARDSHIP_REVIEW")

    assert read_option(blocked["id"])["status"] == "HARDSHIP_BLOCKED"
    assert second["status"] == "PROPOSED"
    assert second["coverage_ratio"] == 1.0

    case = read_case(ctx["case"]["id"])
    assert case["blocked_option_count"] == 1
    assert case["cleared_option_count"] == 0


def test_an_empty_option_table_blocks_the_move_into_hardship_review(api):
    """PRD §3.5: "Exploration ends when the coordinator advances the case from
    `OPTION_EXPLORATION` to `HARDSHIP_REVIEW`, which requires at least one
    option on the case in `PROPOSED` or `CLEARED`. A case with nothing on the
    table is refused with `ERR_NO_OPTIONS_PROPOSED`."

    Design: Difficulty/boundary_precision_check/advance_to_hardship_review_with_zero_options_is_rejected
    """
    set_clock()
    ctx = setup_case_at_option_exploration(department_code="EDU")

    response = api.advance_accommodation_request(
        ctx["case"]["id"], {"target_stage": "HARDSHIP_REVIEW"}, COORD
    )
    validate_error(response, ApiErrorId.ERR_NO_OPTIONS_PROPOSED)

    case = read_case(ctx["case"]["id"])
    assert case["stage"] == "OPTION_EXPLORATION"
    assert case["cleared_option_count"] == 0
    assert case["blocked_option_count"] == 0
    assert case["interactive_round_count"] == 0


def test_a_single_proposed_option_is_enough_to_open_hardship_review(api):
    """PRD §3.5: "Exploration ends when the coordinator advances the case from
    `OPTION_EXPLORATION` to `HARDSHIP_REVIEW`, which requires at least one
    option on the case in `PROPOSED` or `CLEARED`. A case with nothing on the
    table is refused with `ERR_NO_OPTIONS_PROPOSED`."

    Design: Difficulty/boundary_precision_check/advance_to_hardship_review_with_zero_options_is_rejected
    """
    set_clock()
    ctx = setup_case_at_option_exploration(department_code="ED2")

    blocked = api.advance_accommodation_request(
        ctx["case"]["id"], {"target_stage": "HARDSHIP_REVIEW"}, COORD
    )
    validate_error(blocked, ApiErrorId.ERR_NO_OPTIONS_PROPOSED)

    option = propose_option(ctx, option_code="OPT-JUST-ONE")
    assert option["status"] == "PROPOSED"

    allowed = validate_success(
        api.advance_accommodation_request(
            ctx["case"]["id"], {"target_stage": "HARDSHIP_REVIEW"}, COORD
        ),
        200,
    )
    assert allowed["stage"] == "HARDSHIP_REVIEW"
    assert allowed["interactive_round_count"] == 0


def _coverage_and_block_conflict_case(department_code):
    """One option is both under-covering and hardship-blocked; a sibling clears."""
    ctx = setup_case_at_option_exploration(
        functions=TWO_DUTIES,
        department_code=department_code,
        department_annual_budget_cents=1_500_000,
        employer_annual_budget_cents=800_000_000,
    )
    propose_option(
        ctx, covers=[ctx["functions"][1]["id"]], option_code="OPT-VAN-LIFT-2", **HOIST
    )
    propose_option(
        ctx,
        covers="all",
        option_code="OPT-SWAP-2",
        category="JOB_RESTRUCTURING",
        one_time_cost_cents=40_000,
        implementation_days=10,
    )
    advance_case(ctx, "HARDSHIP_REVIEW")
    assess_option(ctx, ctx["options"][0], "SITE_LOCAL")
    assess_option(ctx, ctx["options"][1], "SITE_LOCAL")
    advance_case(ctx, "DECISION_PENDING")
    return ctx


def test_the_coverage_floor_is_reported_ahead_of_the_hardship_block(api):
    """PRD §3.7: "Both grant outcomes are reachable only from stage
    `DECISION_PENDING`, and both require that `selected_option_id` names an
    option on this case whose status is `CLEARED` and whose `coverage_ratio` is
    at least 0.60. An option that leaves too much essential weight uncovered is
    refused with `ERR_ESSENTIAL_FUNCTION_UNCOVERED`; an option that sits in
    `HARDSHIP_BLOCKED` is refused with `ERR_OPTION_HARDSHIP_BLOCKED`. When both
    faults are present on the same request, the coverage failure is the one
    reported, because it is evaluated first."

    Design: Difficulty/priority_pair_validation_conflict/uncovered_essential_function_outranks_hardship_block
    """
    set_clock()
    ctx = _coverage_and_block_conflict_case("DL2")
    under_covering = read_option(ctx["options"][0]["id"])
    assert under_covering["coverage_ratio"] == 0.5
    assert under_covering["status"] == "HARDSHIP_BLOCKED", (
        "the hardship block would also fail this request"
    )

    response = api.decide_accommodation_request(
        ctx["case"]["id"],
        {"decision": "GRANT_WITH_TRIAL", "selected_option_id": under_covering["id"]},
        COORD,
    )
    error = validate_error(response, ApiErrorId.ERR_ESSENTIAL_FUNCTION_UNCOVERED)
    assert error["error_id"] != "ERR_OPTION_HARDSHIP_BLOCKED"
    assert response.status_code == 422


def test_the_rejected_grant_leaves_the_case_and_the_ledger_untouched(api):
    """PRD §3.7: "Both grant outcomes are reachable only from stage
    `DECISION_PENDING`, and both require that `selected_option_id` names an
    option on this case whose status is `CLEARED` and whose `coverage_ratio` is
    at least 0.60. An option that leaves too much essential weight uncovered is
    refused with `ERR_ESSENTIAL_FUNCTION_UNCOVERED`; an option that sits in
    `HARDSHIP_BLOCKED` is refused with `ERR_OPTION_HARDSHIP_BLOCKED`. When both
    faults are present on the same request, the coverage failure is the one
    reported, because it is evaluated first."
    PRD §2.11: "The forward action fires when an option enters `SELECTED` or
    `IMPLEMENTED`: the option's `committed_cost_cents` is set to its
    `option_net_cost_cents`, and that same amount is added to the profile's
    ledger."

    Design: Difficulty/priority_pair_validation_conflict/uncovered_essential_function_outranks_hardship_block
    """
    set_clock()
    ctx = _coverage_and_block_conflict_case("DL3")

    response = api.decide_accommodation_request(
        ctx["case"]["id"],
        {
            "decision": "GRANT_WITH_TRIAL",
            "selected_option_id": ctx["options"][0]["id"],
        },
        COORD,
    )
    validate_error(response, ApiErrorId.ERR_ESSENTIAL_FUNCTION_UNCOVERED)

    case = read_case(ctx["case"]["id"])
    assert case["stage"] == "DECISION_PENDING"
    assert case["selected_option_id"] is None
    assert read_profile(ctx["profile"]["id"])["committed_accommodation_cost_cents"] == 0


def test_a_hardship_blocked_option_with_full_coverage_still_cannot_be_granted(api):
    """PRD §3.7: "Both grant outcomes are reachable only from stage
    `DECISION_PENDING`, and both require that `selected_option_id` names an
    option on this case whose status is `CLEARED` and whose `coverage_ratio` is
    at least 0.60. An option that leaves too much essential weight uncovered is
    refused with `ERR_ESSENTIAL_FUNCTION_UNCOVERED`; an option that sits in
    `HARDSHIP_BLOCKED` is refused with `ERR_OPTION_HARDSHIP_BLOCKED`."

    Design: Corner/errors/corner_hardship_blocked_option_cannot_be_granted
    """
    set_clock()
    ctx = setup_case_at_decision_pending(
        option_specs=[
            dict(option_code="C-OPT-38HI", **UNDUE_SPEC),
            {
                "option_code": "C-OPT-38OK",
                "one_time_cost_cents": 40_000,
                "implementation_days": 10,
            },
        ],
        department_code="CNU",
        department_annual_budget_cents=2_000_000,
        employer_annual_budget_cents=800_000_000,
    )
    blocked, cleared = ctx["options"]
    blocked_now = read_option(blocked["id"])
    assert blocked_now["status"] == "HARDSHIP_BLOCKED"
    assert blocked_now["coverage_ratio"] == 1.0, "the coverage floor is satisfied"
    assert read_option(cleared["id"])["status"] == "CLEARED"

    response = api.decide_accommodation_request(
        ctx["case"]["id"],
        {"decision": "GRANT_PERMANENT", "selected_option_id": blocked["id"]},
        COORD,
    )
    validate_error(response, ApiErrorId.ERR_OPTION_HARDSHIP_BLOCKED)

    case = read_case(ctx["case"]["id"])
    assert case["stage"] == "DECISION_PENDING"
    assert case["selected_option_id"] is None
    assert read_profile(ctx["profile"]["id"])["committed_accommodation_cost_cents"] == 0


def test_a_third_re_entry_into_exploration_exhausts_the_round_allowance(api):
    """PRD §3.6: "That re-entry is capped. A case may re-enter
    `OPTION_EXPLORATION` at most **twice** over its lifetime; a transition that
    would push `interactive_round_count` past two is refused with
    `ERR_INTERACTIVE_ROUND_LIMIT`."
    PRD §3.6: "When instead no option remains `PROPOSED` and
    `cleared_option_count` is zero — every proposal was ruled an undue hardship —
    the parties must keep talking: the coordinator advances the case back from
    `HARDSHIP_REVIEW` to `OPTION_EXPLORATION`, which increments
    `interactive_round_count` by one."

    Design: Corner/errors/corner_interactive_round_limit_blocks_third_exploration
    """
    set_clock()
    ctx = setup_case_at_hardship_review(
        option_specs=[dict(option_code="C-OPT-40A", **UNDUE_SPEC)],
        department_code="CNW",
        department_annual_budget_cents=2_000_000,
        employer_annual_budget_cents=800_000_000,
    )
    first = assess_option(ctx, ctx["options"][0], "SITE_LOCAL")
    assert first["hardship_score"] == 70.00 and first["hardship_verdict"] == "UNDUE"

    for round_index, code in ((1, "C-OPT-40B"), (2, "C-OPT-40C")):
        looped = advance_case(ctx, "OPTION_EXPLORATION")
        assert looped["interactive_round_count"] == round_index
        option = propose_option(ctx, option_code=code, **UNDUE_SPEC)
        advance_case(ctx, "HARDSHIP_REVIEW")
        assessment = assess_option(ctx, option, "SITE_LOCAL")
        assert assessment["hardship_score"] == 70.00
        assert assessment["hardship_verdict"] == "UNDUE"

    response = api.advance_accommodation_request(
        ctx["case"]["id"], {"target_stage": "OPTION_EXPLORATION"}, COORD
    )
    validate_error(response, ApiErrorId.ERR_INTERACTIVE_ROUND_LIMIT)

    case = read_case(ctx["case"]["id"])
    assert case["interactive_round_count"] == 2
    assert case["stage"] == "HARDSHIP_REVIEW"
    assert case["blocked_option_count"] == 3
    assert case["cleared_option_count"] == 0


def test_granting_one_cleared_option_shelves_its_cleared_siblings(api):
    """PRD §3.7: "A `GRANT_WITH_TRIAL` decision moves the chosen option
    `CLEARED → SELECTED`; a `GRANT_PERMANENT` decision moves it
    `CLEARED → IMPLEMENTED`. In both branches the identical fiscal cascade runs:
    the option's `committed_cost_cents` is set to its `option_net_cost_cents`,
    and that amount is added to the pinned profile's
    `committed_accommodation_cost_cents`. In both branches every *other* option
    on the case still sitting in `CLEARED` is moved to `SHELVED`, and the case's
    `cleared_option_count` is recomputed to match."
    PRD §3.7: "Begin with a baseline of **365 days** — one review a year."
    PRD §3.7: "`review_cadence_days` is the smallest of whichever intervals
    apply, and `review_due_date` is the current logical-clock date plus that many
    days."

    Design: Corner/state_machines/corner_grant_shelves_non_selected_cleared_siblings
    """
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_case_at_decision_pending(
        option_specs=[
            {
                "option_code": "C-OPT-20A",
                "one_time_cost_cents": 40_000,
                "implementation_days": 10,
            },
            {
                "option_code": "C-OPT-20B",
                "one_time_cost_cents": 50_000,
                "implementation_days": 5,
            },
        ],
        department_code="CNP",
    )
    option_a, option_b = ctx["options"]
    assert read_option(option_a["id"])["status"] == "CLEARED"
    assert read_option(option_b["id"])["status"] == "CLEARED"
    assert read_case(ctx["case"]["id"])["cleared_option_count"] == 2

    case = decide_case(
        ctx, decision="GRANT_PERMANENT", selected_option_id=option_a["id"]
    )

    assert case["stage"] == "GRANTED_PERMANENT"
    assert case["decision"] == "GRANT_PERMANENT"
    assert case["selected_option_id"] == option_a["id"]
    assert case["cleared_option_count"] == 0
    assert case["review_cadence_days"] == 365
    assert_calendar_date(case["review_due_date"], "2027-08-03", "review_due_date")

    selected = read_option(option_a["id"])
    shelved = read_option(option_b["id"])
    assert selected["status"] == "IMPLEMENTED"
    assert selected["committed_cost_cents"] == 29_600
    assert shelved["status"] == "SHELVED"
    assert shelved["committed_cost_cents"] == 0

    profile = read_profile(ctx["profile"]["id"])
    assert profile["committed_accommodation_cost_cents"] == 29_600
    assert_ledger_matches_options(profile, [selected, shelved])


def test_the_grant_response_already_carries_every_cascade(api):
    """PRD §3.7: "In both branches the case's `decision` and
    `selected_option_id` are written, and the renewal cadence is computed."
    PRD §3.7: "`review_cadence_days` is the smallest of whichever intervals
    apply, and `review_due_date` is the current logical-clock date plus that many
    days."
    PRD §2.11: "The forward action fires when an option enters `SELECTED` or
    `IMPLEMENTED`: the option's `committed_cost_cents` is set to its
    `option_net_cost_cents`, and that same amount is added to the profile's
    ledger."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/corner_grant_response_reflects_every_cascade_immediately
    """
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_case_at_decision_pending(
        option_specs=[
            {
                "option_code": "C-OPT-53",
                "one_time_cost_cents": 40_000,
                "implementation_days": 10,
            }
        ],
        department_code="CNZ",
    )
    option = ctx["options"][0]

    response = api.decide_accommodation_request(
        ctx["case"]["id"],
        {"decision": "GRANT_PERMANENT", "selected_option_id": option["id"]},
        COORD,
    )
    body = validate_success(response, 200)

    assert body["stage"] == "GRANTED_PERMANENT"
    assert body["decision"] == "GRANT_PERMANENT"
    assert body["selected_option_id"] == option["id"]
    assert body["review_cadence_days"] == 365
    assert_calendar_date(body["review_due_date"], "2027-08-03", "review_due_date")

    profile = read_profile(ctx["profile"]["id"])
    assert profile["committed_accommodation_cost_cents"] == 29_600

    stored_option = read_option(option["id"])
    assert stored_option["status"] == "IMPLEMENTED"
    assert stored_option["committed_cost_cents"] == 29_600
