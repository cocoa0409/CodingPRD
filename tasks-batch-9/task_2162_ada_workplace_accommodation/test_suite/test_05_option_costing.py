"""Proposing accommodation options: the credit-adjusted net cost and the
coverage fraction the server derives from them."""

from test_helpers import (
    TEST_USERS,
    assert_accommodation_option,
    assess_option,
    propose_option,
    read_option,
    set_clock,
    setup_case_at_hardship_review,
    setup_case_at_option_exploration,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
FINANCE = TEST_USERS["finance_headers"]


def test_net_cost_and_coverage_are_server_derived_at_proposal(api):
    """PRD §3.5: "Each option's `option_net_cost_cents` is computed from its two
    cost inputs and a **26 percent ADA tax credit**, with recurring spend
    amortised over **24 months**."
    PRD §3.5: "When the denominator set is empty — a pinned profile with no live
    essential duties — the ratio is exactly `1.000000` rather than an error or a
    zero."
    PRD §3.5: "The option is stamped with `proposed_by_role` taken from the
    acting `X-User-Role` — either `Employee` or `AccommodationCoordinator` — is
    born in `status` `PROPOSED` with `committed_cost_cents` at zero, and takes
    its `request_id` from the case being addressed."

    Design: Corner/entities/corner_option_computed_fields_are_server_derived_at_creation
    """
    set_clock()
    ctx = setup_case_at_option_exploration(department_code="CN6")

    response = api.create_accommodation_option(
        ctx["case"]["id"],
        {
            "option_code": "C-OPT-06",
            "category": "TELEWORK",
            "one_time_cost_cents": 50_000,
            "recurring_monthly_cost_cents": 0,
            "implementation_days": 5,
            "coverage_function_ids": [ctx["functions"][0]["id"]],
        },
        COORD,
    )
    data = validate_success(response, 201)

    assert_accommodation_option(data)
    assert data["option_net_cost_cents"] == 37_000, "50000 x (1 - 0.26) is 37000 cents"
    assert data["coverage_ratio"] == 1.0
    assert data["status"] == "PROPOSED"
    assert data["committed_cost_cents"] == 0
    assert data["proposed_by_role"] == "AccommodationCoordinator"
    assert data["request_id"] == ctx["case"]["id"]


def test_each_cost_component_is_rounded_before_the_two_are_added(api):
    """PRD §3.5: "First, the one-time component: multiply `one_time_cost_cents`
    by the credit-adjusted fraction — that is, by one minus 0.26 — and round the
    product half up to a whole number of cents. Second, the recurring component:
    multiply `recurring_monthly_cost_cents` by 24 and then by that same
    credit-adjusted fraction, and round *that* product half up to a whole number
    of cents. Only then are the two rounded components added together to give
    `option_net_cost_cents`."
    PRD §3.5: "Rounding each component independently before summing them is
    mandatory; summing the two unrounded components and rounding once is a
    different computation that yields a different cent figure whenever both
    fractional parts sit below half a cent yet add to half a cent or more."

    Design: Difficulty/combinatorial_formula/option_net_cost_rounds_each_component_before_summing
    """
    set_clock()
    ctx = setup_case_at_option_exploration(department_code="FAC")

    option = propose_option(
        ctx,
        option_code="OPT-LIFT-PLATFORM",
        category="EQUIPMENT",
        one_time_cost_cents=100_003,
        recurring_monthly_cost_cents=4_315,
        implementation_days=30,
    )

    assert option["option_net_cost_cents"] == 150_636, (
        "74002 (rounded) plus 76634 (rounded) is 150636"
    )
    assert option["option_net_cost_cents"] != 150_637, (
        "150637 is the forbidden sum-then-round figure"
    )
    assert option["coverage_ratio"] == 1.0
    assert option["status"] == "PROPOSED"


def test_the_two_rounded_components_are_each_observable_on_their_own(api):
    """PRD §3.5: "First, the one-time component: multiply `one_time_cost_cents`
    by the credit-adjusted fraction — that is, by one minus 0.26 — and round the
    product half up to a whole number of cents. Second, the recurring component:
    multiply `recurring_monthly_cost_cents` by 24 and then by that same
    credit-adjusted fraction, and round *that* product half up to a whole number
    of cents. Only then are the two rounded components added together to give
    `option_net_cost_cents`."
    PRD §2.9: "Wherever a monetary computation produces a fraction, it is
    rounded **half up** to the nearest whole cent — a value ending in exactly
    half a cent rounds away from zero."

    Design: Difficulty/combinatorial_formula/option_net_cost_rounds_each_component_before_summing
    """
    set_clock()
    ctx = setup_case_at_option_exploration(department_code="FA2")

    one_time_only = propose_option(
        ctx,
        option_code="OPT-ONE-TIME-ONLY",
        one_time_cost_cents=100_003,
        recurring_monthly_cost_cents=0,
        implementation_days=30,
    )
    recurring_only = propose_option(
        ctx,
        option_code="OPT-RECURRING-ONLY",
        one_time_cost_cents=0,
        recurring_monthly_cost_cents=4_315,
        implementation_days=30,
    )
    combined = propose_option(
        ctx,
        option_code="OPT-BOTH-COMPONENTS",
        one_time_cost_cents=100_003,
        recurring_monthly_cost_cents=4_315,
        implementation_days=30,
    )

    assert one_time_only["option_net_cost_cents"] == 74_002, (
        "100003 x 0.74 is 74002.22 and rounds half up to 74002"
    )
    assert recurring_only["option_net_cost_cents"] == 76_634, (
        "4315 x 24 x 0.74 is 76634.40 and rounds half up to 76634"
    )
    assert combined["option_net_cost_cents"] == (
        one_time_only["option_net_cost_cents"] + recurring_only["option_net_cost_cents"]
    ), "the combined option is exactly the sum of the two independently rounded parts"
    assert combined["option_net_cost_cents"] == 150_636


def test_the_option_sub_resource_read_carries_the_computed_fields(api):
    """PRD §3.5: "Options on a case are listable with a `status` filter, and any
    option is readable individually together with its net cost, coverage ratio
    and committed amount."
    PRD §2.3: "All four pagination fields — `limit`, `offset`, `total_count` and
    `has_more` — appear in the `meta` object of every list response."

    Design: Corner/endpoints/corner_options_sub_resource_read_returns_computed_fields
    """
    set_clock()
    ctx = setup_case_at_hardship_review(
        option_specs=[
            {"option_code": "C-OPT-31A", "one_time_cost_cents": 40_000, "implementation_days": 10},
            {"option_code": "C-OPT-31B", "one_time_cost_cents": 50_000, "implementation_days": 5},
        ],
        department_code="CNO",
    )
    option_a, option_b = ctx["options"]
    assess_option(ctx, option_a, "SITE_LOCAL")
    assert read_option(option_a["id"])["status"] == "CLEARED"

    rows, meta = validate_paginated(
        api.list_request_options(ctx["case"]["id"], FINANCE, {"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    by_id = {row["id"]: row for row in rows}
    assert by_id[option_a["id"]]["option_net_cost_cents"] == 29_600
    assert by_id[option_a["id"]]["coverage_ratio"] == 1.0
    assert by_id[option_b["id"]]["option_net_cost_cents"] == 37_000
    assert by_id[option_b["id"]]["coverage_ratio"] == 1.0

    cleared, cleared_meta = validate_paginated(
        api.list_request_options(ctx["case"]["id"], FINANCE, {"status": "CLEARED"})
    )
    assert cleared_meta["total_count"] == 1
    assert cleared[0]["id"] == option_a["id"]
