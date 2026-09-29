"""The finance officer's undue-hardship assessment: the pinned formula, the
mitigation band and the clearing fork."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_case,
    assert_hardship_assessment,
    assess_option,
    api_client,
    create_function_analysis_payload,
    essential_function_ids,
    record_all_analyses,
    option_version,
    propose_option,
    read_case,
    read_option,
    set_clock,
    setup_case_at_function_analysis,
    setup_case_at_hardship_review,
    setup_case_at_option_exploration,
    validate_error,
    validate_paginated,
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


def _twin_option_case(department_code):
    """Two byte-identical options, each covering one of two equal duties."""
    ctx = setup_case_at_option_exploration(
        functions=TWO_DUTIES,
        department_code=department_code,
        department_annual_budget_cents=1_500_000,
        employer_annual_budget_cents=800_000_000,
    )
    covered = [ctx["functions"][0]["id"]]
    propose_option(ctx, covers=covered, option_code="OPT-HOIST-A", **HOIST)
    propose_option(ctx, covers=covered, option_code="OPT-HOIST-B", **HOIST)
    advance_case(ctx, "HARDSHIP_REVIEW")
    return ctx


def test_the_site_local_basis_drives_the_identical_option_to_undue(api):
    """PRD §3.6: "**Choose the denominator.** `denominator_cents` is the pinned
    profile's `employer_annual_budget_cents` when `assessment_basis` is
    `EMPLOYER_WIDE`, and the pinned profile's `department_annual_budget_cents`
    when it is `SITE_LOCAL`."
    PRD §3.6: "**Budget ratio.** `budget_ratio` is `assessed_net_cost_cents`
    divided by `denominator_cents`, rounded half up to six decimal places."
    PRD §3.6: "**Pre-credit score.** `raw_hardship_score` is `budget_ratio_norm`
    multiplied by **0.65**, plus `disruption_index` multiplied by **0.20**, plus
    `lag_norm` multiplied by **0.15**, with the sum rounded half up to two
    decimal places."
    PRD §3.6: "**Verdict.** `hardship_verdict` is `UNDUE` when `hardship_score`
    is at least `70.00`; otherwise `BORDERLINE` when `hardship_score` is at
    least `45.00`; otherwise `NOT_UNDUE`."
    PRD §3.6: "**Branch B — blocked.** A verdict of `UNDUE` moves the option
    `PROPOSED → HARDSHIP_BLOCKED`, increments the case's `blocked_option_count`
    by one, and increments the option's `version` by one."

    Design: Difficulty/dual_variant_calc/hardship_basis_variant_flips_verdict_on_identical_option
    """
    set_clock()
    ctx = _twin_option_case("OPS")
    option_a = ctx["options"][0]
    assert option_a["option_net_cost_cents"] == 150_636

    assessment = assess_option(ctx, option_a, "SITE_LOCAL")
    assert_hardship_assessment(assessment)

    assert assessment["assessed_net_cost_cents"] == 150_636
    assert assessment["denominator_cents"] == 1_500_000
    assert assessment["budget_ratio"] == 0.100424
    assert assessment["budget_ratio_norm"] == 100.0, "the norm saturates at the cap"
    assert assessment["disruption_index"] == 50.0
    assert assessment["lag_norm"] == 50.0
    assert assessment["raw_hardship_score"] == 82.5
    assert assessment["mitigation_credit_rate"] == 0.05
    assert assessment["hardship_score"] == 78.38
    assert assessment["hardship_verdict"] == "UNDUE"

    assert read_option(option_a["id"])["status"] == "HARDSHIP_BLOCKED"
    case = read_case(ctx["case"]["id"])
    assert case["blocked_option_count"] == 1
    assert case["cleared_option_count"] == 0


def test_the_employer_wide_basis_clears_the_very_same_option(api):
    """PRD §3.6: "**Choose the denominator.** `denominator_cents` is the pinned
    profile's `employer_annual_budget_cents` when `assessment_basis` is
    `EMPLOYER_WIDE`, and the pinned profile's `department_annual_budget_cents`
    when it is `SITE_LOCAL`."
    PRD §3.6: "**Normalise the budget pressure.** Divide `budget_ratio` by a cap
    of **0.05** — five percent of the applicable budget is treated as the point
    of maximum cost pressure — multiply by 100, round half up to four decimal
    places, and then take the smaller of that figure and `100.0000`. The result
    is `budget_ratio_norm`."
    PRD §3.6: "**Branch A — cleared.** A verdict of `NOT_UNDUE` or of
    `BORDERLINE` moves the option `PROPOSED → CLEARED`, increments the case's
    `cleared_option_count` by one, and increments the option's `version` by one."
    PRD §3.6: "Same option, same coverage, same lead time: divergent verdict,
    and divergent option status."

    Design: Difficulty/dual_variant_calc/hardship_basis_variant_flips_verdict_on_identical_option
    """
    set_clock()
    ctx = _twin_option_case("OP2")
    option_a, option_b = ctx["options"]
    assert (
        option_a["option_net_cost_cents"] == option_b["option_net_cost_cents"] == 150_636
    )

    site_local = assess_option(ctx, option_a, "SITE_LOCAL")
    employer_wide = assess_option(ctx, option_b, "EMPLOYER_WIDE")

    assert employer_wide["assessed_net_cost_cents"] == 150_636
    assert employer_wide["denominator_cents"] == 800_000_000
    assert employer_wide["budget_ratio"] == 0.000188
    assert employer_wide["budget_ratio_norm"] == 0.376
    assert employer_wide["raw_hardship_score"] == 17.74
    assert employer_wide["mitigation_credit_rate"] == 0.0
    assert employer_wide["hardship_score"] == 17.74
    assert employer_wide["hardship_verdict"] == "NOT_UNDUE"

    assert site_local["hardship_verdict"] == "UNDUE"
    assert read_option(option_a["id"])["status"] == "HARDSHIP_BLOCKED"
    assert read_option(option_b["id"])["status"] == "CLEARED"

    case = read_case(ctx["case"]["id"])
    assert case["blocked_option_count"] == 1
    assert case["cleared_option_count"] == 1


def _bench_rig_case(department_code):
    ctx = setup_case_at_hardship_review(
        option_specs=[
            {
                "option_code": "OPT-BENCH-RIG",
                "one_time_cost_cents": 106_030,
                "recurring_monthly_cost_cents": 0,
                "implementation_days": 60,
            }
        ],
        department_code=department_code,
        department_annual_budget_cents=2_000_000,
        employer_annual_budget_cents=800_000_000,
    )
    return ctx


def test_the_mitigation_band_is_read_off_the_pre_credit_score(api):
    """PRD §3.6: "**Mitigation credit.** `mitigation_credit_rate` is selected
    from a band read off `raw_hardship_score`. When `raw_hardship_score` is
    below `40.00` the rate is `0.00`. When it is at least `40.00` but below
    `65.00` the rate is `0.10`. When it is at least `65.00` but below `85.00` the
    rate is `0.05`. When it is `85.00` or above the rate is `0.00`. The tier is
    read from the **pre-credit** figure, always; it is never re-selected from the
    post-credit figure even when the credit pushes the score down into a lower
    band, and the credit is applied exactly once."
    PRD §3.6: "**Final score.** `hardship_score` is `raw_hardship_score`
    multiplied by one minus `mitigation_credit_rate`, rounded half up to two
    decimal places."

    Design: Difficulty/combinatorial_formula/mitigation_credit_tier_read_from_pre_credit_raw_score
    """
    set_clock()
    ctx = _bench_rig_case("LAB")
    assessment = assess_option(ctx, ctx["options"][0], "SITE_LOCAL")

    assert assessment["raw_hardship_score"] == 66.0
    assert assessment["mitigation_credit_rate"] == 0.05, (
        "66.00 sits in the 65.00-to-85.00 band"
    )
    assert assessment["hardship_score"] == 62.70
    assert assessment["hardship_score"] != 59.40, (
        "59.40 is what re-selecting the band from the post-credit figure would give"
    )
    assert assessment["hardship_verdict"] == "BORDERLINE"


def test_the_mitigation_credit_is_applied_exactly_once(api):
    """PRD §3.6: "**Snapshot the cost.** `assessed_net_cost_cents` is a copy of
    the option's `option_net_cost_cents` taken at assessment time; a later
    revision of the option never rewrites it."
    PRD §3.6: "**Disruption.** `disruption_index` is the uncovered share of
    essential weight on the same scale: subtract the option's `coverage_ratio`
    from 1, multiply by 100, and round half up to four decimal places."
    PRD §3.6: "**Lag.** Divide the option's `implementation_days` by a cap of
    **60 days**, multiply by 100, round half up to four decimal places, and take
    the smaller of that figure and `100.0000`. The result is `lag_norm`."
    PRD §3.6: "**Mitigation credit.** `mitigation_credit_rate` is selected from a
    band read off `raw_hardship_score`. When `raw_hardship_score` is below
    `40.00` the rate is `0.00`. When it is at least `40.00` but below `65.00` the
    rate is `0.10`. When it is at least `65.00` but below `85.00` the rate is
    `0.05`. When it is `85.00` or above the rate is `0.00`. The tier is read from
    the **pre-credit** figure, always; it is never re-selected from the
    post-credit figure even when the credit pushes the score down into a lower
    band, and the credit is applied exactly once."
    PRD §3.6: "**Branch A — cleared.** A verdict of `NOT_UNDUE` or of
    `BORDERLINE` moves the option `PROPOSED → CLEARED`, increments the case's
    `cleared_option_count` by one, and increments the option's `version` by one."

    Design: Difficulty/combinatorial_formula/mitigation_credit_tier_read_from_pre_credit_raw_score
    """
    set_clock()
    ctx = _bench_rig_case("LA2")
    option = ctx["options"][0]
    assert option["option_net_cost_cents"] == 78_462

    assessment = assess_option(ctx, option, "SITE_LOCAL")

    assert assessment["assessed_net_cost_cents"] == 78_462
    assert assessment["budget_ratio"] == 0.039231
    assert assessment["budget_ratio_norm"] == 78.462
    assert assessment["disruption_index"] == 0.0
    assert assessment["lag_norm"] == 100.0, "60 implementation days saturates the 60-day cap"
    assert assessment["raw_hardship_score"] == 66.0
    assert assessment["hardship_score"] == 62.70, (
        "the credit is applied once: 66.00 x 0.95, not 66.00 x 0.95 x 0.95"
    )
    assert assessment["status"] == "CURRENT"

    assert read_option(option["id"])["status"] == "CLEARED"
    assert read_case(ctx["case"]["id"])["cleared_option_count"] == 1


def _welder_case(department_code):
    return setup_case_at_hardship_review(
        option_specs=[
            {
                "option_code": "OPT-EDGE-HIGH",
                "one_time_cost_cents": 121_995,
                "recurring_monthly_cost_cents": 0,
                "implementation_days": 60,
            },
            {
                "option_code": "OPT-EDGE-LOW",
                "one_time_cost_cents": 121_984,
                "recurring_monthly_cost_cents": 0,
                "implementation_days": 60,
            },
        ],
        department_code=department_code,
        department_annual_budget_cents=2_000_000,
        employer_annual_budget_cents=800_000_000,
    )


def test_a_score_of_exactly_seventy_is_an_undue_hardship(api):
    """PRD §3.6: "**Verdict.** `hardship_verdict` is `UNDUE` when
    `hardship_score` is at least `70.00`; otherwise `BORDERLINE` when
    `hardship_score` is at least `45.00`; otherwise `NOT_UNDUE`."
    PRD §3.6: "**Branch B — blocked.** A verdict of `UNDUE` moves the option
    `PROPOSED → HARDSHIP_BLOCKED`, increments the case's `blocked_option_count`
    by one, and increments the option's `version` by one."

    Design: Difficulty/boundary_precision_check/hardship_score_exactly_at_undue_threshold_is_undue
    """
    set_clock()
    ctx = _welder_case("MFG")
    high = ctx["options"][0]
    assert high["option_net_cost_cents"] == 90_276

    assessment = assess_option(ctx, high, "SITE_LOCAL")
    assert assessment["budget_ratio"] == 0.045138
    assert assessment["budget_ratio_norm"] == 90.276
    assert assessment["raw_hardship_score"] == 73.68
    assert assessment["mitigation_credit_rate"] == 0.05
    assert assessment["hardship_score"] == 70.00, "exactly at the threshold"
    assert assessment["hardship_verdict"] == "UNDUE"

    assert read_option(high["id"])["status"] == "HARDSHIP_BLOCKED"
    assert read_case(ctx["case"]["id"])["blocked_option_count"] == 1


def test_a_score_one_hundredth_below_the_threshold_is_only_borderline(api):
    """PRD §3.6: "**Verdict.** `hardship_verdict` is `UNDUE` when
    `hardship_score` is at least `70.00`; otherwise `BORDERLINE` when
    `hardship_score` is at least `45.00`; otherwise `NOT_UNDUE`."
    PRD §3.6: "**Branch A — cleared.** A verdict of `NOT_UNDUE` or of
    `BORDERLINE` moves the option `PROPOSED → CLEARED`, increments the case's
    `cleared_option_count` by one, and increments the option's `version` by one."

    Design: Difficulty/boundary_precision_check/hardship_score_exactly_at_undue_threshold_is_undue
    """
    set_clock()
    ctx = _welder_case("MF2")
    high, low = ctx["options"]
    assert low["option_net_cost_cents"] == 90_268

    high_assessment = assess_option(ctx, high, "SITE_LOCAL")
    low_assessment = assess_option(ctx, low, "SITE_LOCAL")

    assert low_assessment["budget_ratio"] == 0.045134
    assert low_assessment["budget_ratio_norm"] == 90.268
    assert low_assessment["raw_hardship_score"] == 73.67
    assert low_assessment["hardship_score"] == 69.99
    assert low_assessment["hardship_verdict"] == "BORDERLINE"
    assert high_assessment["hardship_score"] == 70.00

    assert read_option(low["id"])["status"] == "CLEARED"
    assert read_option(high["id"])["status"] == "HARDSHIP_BLOCKED"

    case = read_case(ctx["case"]["id"])
    assert case["blocked_option_count"] == 1
    assert case["cleared_option_count"] == 1


def _retired_duty_case(department_code):
    ctx = setup_case_at_hardship_review(
        option_specs=[{"option_code": "OPT-BOTH", "covers": "all"}],
        functions=TWO_DUTIES,
        department_code=department_code,
        department_annual_budget_cents=1_500_000,
        employer_annual_budget_cents=800_000_000,
    )
    retired = validate_success(
        api_client.update_essential_function(
            ctx["functions"][1]["id"], {"status": "RETIRED"}, COORD
        ),
        200,
    )
    assert retired["status"] == "RETIRED"
    return ctx


def _case_at_function_analysis_with_one_analysis(department_code):
    ctx = setup_case_at_function_analysis(department_code=department_code)
    record_all_analyses(ctx)
    return ctx


def test_an_assessment_over_a_retired_duty_is_refused(api):
    """PRD §3.6: "Three preconditions gate the write: the case must be in stage
    `HARDSHIP_REVIEW`, every duty referenced by the option's
    `coverage_function_ids` must still be `ACTIVE` and must still belong to the
    case's pinned `job_profile_id` (otherwise
    `ERR_FUNCTION_NOT_IN_PINNED_PROFILE`), and the supplied version must match."
    PRD §3.1: "Duties can be revised after authoring, by either an
    `AccommodationCoordinator` or a `Manager`, adjusting any of
    `criticality_weight`, `frequency_per_week`, `is_essential`,
    `marginal_reassignable` and `status`."

    Design: Difficulty/cross_entity_state_dependency/assessment_blocked_by_retired_essential_function
    """
    set_clock()
    ctx = _retired_duty_case("GRO")
    option = ctx["options"][0]

    response = api.create_hardship_assessment(
        option["id"],
        {
            "assessment_basis": "SITE_LOCAL",
            "expected_option_version": option_version(option["id"]),
        },
        FINANCE,
    )
    validate_error(response, ApiErrorId.ERR_FUNCTION_NOT_IN_PINNED_PROFILE)

    assert read_option(option["id"])["status"] == "PROPOSED"
    _rows, meta = validate_paginated(api.list_hardship_assessments(option["id"], FINANCE))
    assert meta["total_count"] == 0


def test_retiring_a_duty_reshapes_the_roll_ups_and_the_coverage_arithmetic(api):
    """PRD §3.1: "Three consequences follow every revision. The profile's
    `essential_function_count` and `total_essential_weight` are recomputed. Then
    the coverage fraction is recomputed for **every** accommodation option
    belonging to a case pinned to this profile whose option `status` is
    `PROPOSED`, `CLEARED` or `HARDSHIP_BLOCKED` — retiring a heavily weighted
    duty silently reshapes the coverage arithmetic of options that were priced
    before the retirement."
    PRD §3.5: "Marginal duties and retired duties are excluded from **both**
    numerator and denominator, and an id listed in `coverage_function_ids` that
    falls outside the filtered denominator set contributes nothing at all."

    Design: Difficulty/cross_entity_state_dependency/assessment_blocked_by_retired_essential_function
    """
    set_clock()
    ctx = _retired_duty_case("GR2")
    option = ctx["options"][0]

    profile = validate_success(api.get_job_profile(ctx["profile"]["id"], COORD), 200)
    assert profile["total_essential_weight"] == 5
    assert profile["essential_function_count"] == 1

    refreshed = read_option(option["id"])
    assert refreshed["coverage_ratio"] == 1.0, (
        "the retired duty left both the numerator and the denominator"
    )
    assert refreshed["status"] == "PROPOSED"


def test_revising_a_blocked_option_returns_it_to_the_assessment_queue(api):
    """PRD §3.5: "From `HARDSHIP_BLOCKED` the revision is a genuine cycle back
    into the assessment queue: the option returns to `PROPOSED`, the case's
    `blocked_option_count` is decremented, and the option's current
    undue-hardship assessment is moved to `SUPERSEDED`."
    PRD §3.5: "Whatever the option's starting status, revision recomputes both
    `option_net_cost_cents` and `coverage_ratio` and increments the option's
    `version`."
    PRD §3.6: "Every assessment is created in `status` `CURRENT` and moves any
    prior `CURRENT` assessment on the same option to `SUPERSEDED`; assessments on
    an option are listable with a `status` filter."

    Design: Corner/state_machines/corner_option_revision_cycles_hardship_blocked_back_to_proposed
    """
    set_clock()
    ctx = setup_case_at_hardship_review(
        option_specs=[
            {
                "option_code": "C-OPT-19",
                "one_time_cost_cents": 121_995,
                "recurring_monthly_cost_cents": 0,
                "implementation_days": 60,
            }
        ],
        department_code="CNR",
        department_annual_budget_cents=2_000_000,
        employer_annual_budget_cents=800_000_000,
    )
    option = ctx["options"][0]
    first_assessment = assess_option(ctx, option, "SITE_LOCAL")
    assert first_assessment["hardship_verdict"] == "UNDUE"
    assert read_option(option["id"])["status"] == "HARDSHIP_BLOCKED"
    assert read_case(ctx["case"]["id"])["blocked_option_count"] == 1

    revised = validate_success(
        api.update_accommodation_option(
            option["id"], {"one_time_cost_cents": 40_000, "implementation_days": 10}, COORD
        ),
        200,
    )
    assert revised["status"] == "PROPOSED"
    assert revised["option_net_cost_cents"] == 29_600
    assert read_case(ctx["case"]["id"])["blocked_option_count"] == 0

    rows, _meta = validate_paginated(api.list_hardship_assessments(option["id"], FINANCE))
    superseded = [r for r in rows if r["id"] == first_assessment["id"]][0]
    assert superseded["status"] == "SUPERSEDED"

    second_assessment = assess_option(ctx, option, "SITE_LOCAL")
    assert second_assessment["hardship_score"] == 21.74
    assert second_assessment["hardship_verdict"] == "NOT_UNDUE"

    assert read_option(option["id"])["status"] == "CLEARED"
    assert read_case(ctx["case"]["id"])["cleared_option_count"] == 1

    _rows, meta = validate_paginated(api.list_hardship_assessments(option["id"], FINANCE))
    assert meta["total_count"] == 2


def test_the_assessment_sequencing_guards_fire_one_at_a_time(api):
    """PRD §3.4: "And a case may hold only one live analysis per duty: if an
    analysis for the same `essential_function_id` already exists on this case in
    `RECORDED` or in `DISPUTED`, the attempt is refused with
    `ERR_DUPLICATE_FUNCTION_ANALYSIS`."
    PRD §3.6: "An assessment against an option whose status does not admit one,
    or against a case outside `HARDSHIP_REVIEW`, is refused with
    `ERR_OPTION_NOT_ASSESSABLE`."
    PRD §3.6: "When no option on the case remains `PROPOSED` and
    `cleared_option_count` is at least 1, an `AccommodationCoordinator` advances
    the case from `HARDSHIP_REVIEW` to `DECISION_PENDING`; an advance attempted
    while an option is still awaiting assessment, or with `cleared_option_count`
    at zero, is refused with `ERR_OPTION_ASSESSMENT_PENDING`."

    Design: Corner/errors/corner_option_assessment_sequencing_guard_rails
    """
    set_clock()
    ctx = _case_at_function_analysis_with_one_analysis("CNT")
    function_id = essential_function_ids(ctx)[0]

    duplicate = api.create_function_analysis(
        ctx["case"]["id"],
        create_function_analysis_payload(
            function_id,
            can_perform_unaided=True,
            limitation_severity=0,
            proposed_treatment="NOT_LIMITED",
        ),
        ctx["manager_headers"],
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_FUNCTION_ANALYSIS)
    _rows, meta = validate_paginated(
        api.list_function_analyses(COORD, {"request_id": ctx["case"]["id"]})
    )
    assert meta["total_count"] == 1

    advance_case(ctx, "OPTION_EXPLORATION")
    option_a = propose_option(
        ctx, option_code="C-OPT-33A", one_time_cost_cents=40_000, implementation_days=10
    )

    premature = api.create_hardship_assessment(
        option_a["id"],
        {
            "assessment_basis": "SITE_LOCAL",
            "expected_option_version": option_a["version"],
        },
        FINANCE,
    )
    validate_error(premature, ApiErrorId.ERR_OPTION_NOT_ASSESSABLE)
    assert read_option(option_a["id"])["status"] == "PROPOSED"

    option_b = propose_option(
        ctx,
        option_code="C-OPT-33B",
        category="TELEWORK",
        one_time_cost_cents=50_000,
        implementation_days=5,
    )
    advance_case(ctx, "HARDSHIP_REVIEW")
    assess_option(ctx, option_a, "SITE_LOCAL")
    assert read_option(option_a["id"])["status"] == "CLEARED"
    assert read_case(ctx["case"]["id"])["cleared_option_count"] == 1

    pending = api.advance_accommodation_request(
        ctx["case"]["id"], {"target_stage": "DECISION_PENDING"}, COORD
    )
    validate_error(pending, ApiErrorId.ERR_OPTION_ASSESSMENT_PENDING)
    assert read_option(option_b["id"])["status"] == "PROPOSED"
    assert read_case(ctx["case"]["id"])["stage"] == "HARDSHIP_REVIEW"
