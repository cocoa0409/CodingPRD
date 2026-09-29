"""The manager's duty-by-duty essential-function analysis and the completeness
gate out of the analysis stage."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_function_analysis,
    create_function_analysis_payload,
    essential_function_ids,
    propose_option,
    read_case,
    record_analysis,
    set_clock,
    setup_case_at_function_analysis,
    setup_case_at_option_exploration,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_the_analysis_junction_resolves_from_either_side_and_from_the_manager(api):
    """PRD §3.4: "The analysis takes its `request_id` from the case being
    addressed and stamps `manager_id` from the acting `X-User-ID`; both are
    server-set and cannot be supplied."
    PRD §3.4: "Every new analysis is born in `status` `RECORDED` with
    `employee_dispute_note` null."
    PRD §3.4: "Analyses are readable individually and listable with filters on
    `request_id`, `essential_function_id`, `manager_id` and `status`."

    Design: Corner/entities/corner_function_analysis_junction_links_request_and_function
    """
    set_clock()
    ctx = setup_case_at_function_analysis(department_code="CNB")
    function_id = essential_function_ids(ctx)[0]

    created = validate_success(
        api.create_function_analysis(
            ctx["case"]["id"],
            create_function_analysis_payload(
                function_id,
                can_perform_unaided=False,
                limitation_severity=2,
                proposed_treatment="RESTRUCTURE",
            ),
            ctx["manager_headers"],
        ),
        201,
    )
    assert_function_analysis(created)
    assert created["status"] == "RECORDED"
    assert created["employee_dispute_note"] is None
    assert created["manager_id"] == ctx["manager"]["id"]
    assert created["request_id"] == ctx["case"]["id"]

    by_function, meta_function = validate_paginated(
        api.list_function_analyses(AUDITOR, {"essential_function_id": function_id})
    )
    assert meta_function["total_count"] == 1
    assert by_function[0]["id"] == created["id"]
    assert by_function[0]["request_id"] == ctx["case"]["id"]

    by_manager, meta_manager = validate_paginated(
        api.list_function_analyses(AUDITOR, {"manager_id": ctx["manager"]["id"]})
    )
    assert meta_manager["total_count"] == 1
    assert by_manager[0]["id"] == created["id"]

    single = validate_success(api.get_function_analysis(created["id"], AUDITOR), 200)
    assert single["essential_function_id"] == function_id


def test_a_missing_analysis_blocks_the_move_into_option_exploration(api):
    """PRD §3.4: "An `AccommodationCoordinator` advances the case from
    `FUNCTION_ANALYSIS` to `OPTION_EXPLORATION` by naming that `target_stage`,
    and the advance succeeds only when **every** duty on the pinned profile that
    is simultaneously `is_essential` true and `status` `ACTIVE` has exactly one
    analysis on this case in `status` `RECORDED`."
    PRD §3.4: "A missing analysis, a duplicate, or a lone disputed analysis all
    leave the requirement unmet, and the advance is refused with
    `ERR_FUNCTION_ANALYSIS_INCOMPLETE`."

    Design: Corner/state_machines/corner_advance_to_option_exploration_with_incomplete_analyses_rejected
    """
    set_clock()
    ctx = setup_case_at_function_analysis(
        functions=({"criticality_weight": 5}, {"criticality_weight": 5}),
        department_code="CND",
    )
    record_analysis(ctx, essential_function_ids(ctx)[0])

    response = api.advance_accommodation_request(
        ctx["case"]["id"], {"target_stage": "OPTION_EXPLORATION"}, COORD
    )
    validate_error(response, ApiErrorId.ERR_FUNCTION_ANALYSIS_INCOMPLETE)

    assert read_case(ctx["case"]["id"])["stage"] == "FUNCTION_ANALYSIS"

    _rows, meta = validate_paginated(
        api.list_function_analyses(AUDITOR, {"request_id": ctx["case"]["id"]})
    )
    assert meta["total_count"] == 1


def test_a_marginal_duty_leaves_both_sides_of_the_coverage_fraction(api):
    """PRD §3.5: "The denominator is the set of duties on the case's pinned job
    profile that are simultaneously `is_essential` true and `status` `ACTIVE`;
    the numerator is the subset of *those* duties whose ids appear in the
    option's `coverage_function_ids`."
    PRD §3.5: "Marginal duties and retired duties are excluded from **both**
    numerator and denominator, and an id listed in `coverage_function_ids` that
    falls outside the filtered denominator set contributes nothing at all."
    PRD §3.1: "`total_essential_weight` is the sum of `criticality_weight` over
    the profile's duties that are simultaneously `is_essential` true and
    `status` `ACTIVE`; marginal duties and retired duties contribute nothing to
    it."
    PRD §3.1: "`essential_function_count` is the number of duties on the profile
    whose `status` is `ACTIVE`, regardless of whether they are essential or
    marginal."

    Design: Corner/calculations/corner_coverage_ratio_excludes_marginal_functions_from_both_terms
    """
    set_clock()
    ctx = setup_case_at_option_exploration(
        functions=(
            {"criticality_weight": 6, "is_essential": True, "marginal_reassignable": False},
            {"criticality_weight": 4, "is_essential": False, "marginal_reassignable": True},
        ),
        department_code="CNM",
    )

    profile = validate_success(api.get_job_profile(ctx["profile"]["id"], COORD), 200)
    assert profile["total_essential_weight"] == 6, "the marginal weight of 4 is excluded"
    assert profile["essential_function_count"] == 2, (
        "the count takes every ACTIVE duty, essential or marginal"
    )

    essential = ctx["functions"][0]
    option = propose_option(ctx, covers=[essential["id"]], option_code="C-OPT-21A")
    assert option["coverage_ratio"] == 1.0, (
        "6 of 6 essential weight is covered once the marginal duty leaves both terms"
    )

    _rows, meta = validate_paginated(
        api.list_request_options(ctx["case"]["id"], COORD)
    )
    assert meta["total_count"] == 1
