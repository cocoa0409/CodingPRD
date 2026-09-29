"""Pricing financing options and the two independent project axes."""
from test_helpers import (
    validate_success, validate_paginated,
    assert_financing_scenario,
    financing_scenario_payload,
    setup_intake_project, setup_permitted_project,
    price_financing_scenario, current_project_version, read_project,
    run_screening, lock_pathway, add_utility_connection, decide_utility_connection,
    prepare_submittal, file_submittal, approve_plan_check,
    FINANCE_ADVISOR,
)


def test_sales_comparison_appraisal_leaves_a_funding_gap(api):
    """PRD §3.5: "Under `SALES_COMPARISON`, `as_completed_value_cents` is the parcel's
    `pre_adu_value_cents` plus nothing more than `comparable_adjustment_cents` — the
    contributory value the appraiser could defend from comparable sales, which in most
    California submarkets lands far below what the unit cost to build."
    PRD §3.5: "`required_funds_cents` is the project's `contract_price_current_cents` as it
    stands at evaluation time, plus the project's `total_permit_fee_cents`, plus a soft-cost
    contingency of 10 percent of `contract_price_current_cents` rounded half away from zero
    to whole cents."
    PRD §3.5: "Finally `appraisal_shortfall` is true when the value the ADU actually added —
    `as_completed_value_cents` less the parcel's `pre_adu_value_cents` — is strictly less than
    `required_funds_cents`, which is the polite way of saying the homeowner will not get their
    money back on paper."

    Design: Difficulty/dual_variant_calc/appraisal_approach_funding_gap_divergence
    """
    ctx = setup_permitted_project(api)
    assert ctx["project"]["total_permit_fee_cents"] == 1_120_465

    version = current_project_version(api, ctx["project"]["id"])
    scenario = validate_success(api.create_financing_scenario(
        ctx["project"]["id"],
        financing_scenario_payload(version, product_type="HELOC",
                                   appraisal_approach="SALES_COMPARISON"),
        FINANCE_ADVISOR), 201)

    assert_financing_scenario(scenario)
    assert scenario["as_completed_value_cents"] == 89_000_000
    assert scenario["max_loan_cents"] == 71_200_000
    assert scenario["available_cents"] == 11_200_000
    assert scenario["required_funds_cents"] == 27_520_465
    assert scenario["funding_gap_cents"] == 16_320_465
    assert scenario["appraisal_shortfall"] is True


def test_income_capitalization_appraisal_closes_the_funding_gap(api):
    """PRD §3.5: "Under `INCOME_CAPITALIZATION`, `as_completed_value_cents` is the parcel's
    `pre_adu_value_cents` plus the capitalized net rent: take `projected_monthly_rent_cents`,
    annualize it by multiplying by 12, apply a vacancy factor of 0.92 and then an
    operating-expense haircut that retains 65 percent of what remains (that is, multiply by
    one minus an expense ratio of 0.35), divide the result by a capitalization rate of 0.055,
    round that capitalized figure half away from zero to whole cents, and add it to the
    pre-ADU value."
    PRD §3.5: "`max_loan_cents` is `as_completed_value_cents` multiplied by a platform
    loan-to-value ceiling of 0.80, **truncated toward zero** rather than rounded — this is the
    one place in the API that floors instead of rounding half up."
    PRD §3.5: "Creating a scenario supersedes whatever came before it: any scenario of the
    same project still in `ACTIVE` moves to `SUPERSEDED`, and the new row is created in
    `ACTIVE` with every derived field stamped."

    Design: Difficulty/dual_variant_calc/appraisal_approach_funding_gap_divergence
    """
    ctx = setup_permitted_project(api)
    sales = price_financing_scenario(api, ctx["project"]["id"], product_type="HELOC",
                                     appraisal_approach="SALES_COMPARISON")

    income = price_financing_scenario(api, ctx["project"]["id"],
                                      product_type="CONSTRUCTION_LOAN",
                                      appraisal_approach="INCOME_CAPITALIZATION")

    assert income["as_completed_value_cents"] == 112_618_182
    assert income["max_loan_cents"] == 90_094_545, "0.80 of 112618182 truncates toward zero"
    assert income["available_cents"] == 30_094_545
    assert income["required_funds_cents"] == 27_520_465
    assert income["funding_gap_cents"] == 0
    assert income["appraisal_shortfall"] is False

    superseded = validate_success(api.get_financing_scenario(sales["id"], FINANCE_ADVISOR))
    assert superseded["status"] == "SUPERSEDED"
    assert read_project(api, ctx["project"]["id"])["financing_state"] == "PRE_QUALIFIED"


def test_design_axis_advances_while_the_funding_axis_stays_unfunded(api):
    """PRD §2.9: "An ADU project carries two independent state fields on the same row.
    `status` is the design, permit, and build lifecycle, taking values from `INTAKE`,
    `FEASIBILITY_CLEARED`, `PERMITTING`, `DESIGN_REVISION`, `PERMITTED`,
    `UNDER_CONSTRUCTION`, and `FINALED`; it begins at `INTAKE` and `FINALED` is terminal.
    `financing_state` is the funding lifecycle, taking values from `UNFUNDED`,
    `PRE_QUALIFIED`, `COMMITTED`, and `SHORTFALL`; it begins at `UNFUNDED` and has no terminal
    value. The two axes advance on unrelated triggers and never gate one another except where
    a rule below explicitly says so."

    Design: Difficulty/non_linear_state_machine/project_parallel_state_axes
    """
    ctx = setup_intake_project(api)
    assert ctx["project"]["status"] == "INTAKE"
    assert ctx["project"]["financing_state"] == "UNFUNDED"

    screening = run_screening(api, ctx["project"]["id"], "LOCAL_ORDINANCE")
    cleared = lock_pathway(api, ctx["project"]["id"], screening["id"])
    assert cleared["status"] == "FEASIBILITY_CLEARED"
    assert cleared["financing_state"] == "UNFUNDED"

    connection = add_utility_connection(api, ctx["project"]["id"], "ELECTRIC")
    decide_utility_connection(api, connection["id"])
    submittal = prepare_submittal(api, ctx["project"]["id"])
    file_submittal(api, submittal["id"])
    permitting = read_project(api, ctx["project"]["id"])
    assert permitting["status"] == "PERMITTING"
    assert permitting["financing_state"] == "UNFUNDED"

    approve_plan_check(api, submittal["id"])
    permitted = read_project(api, ctx["project"]["id"])
    assert permitted["status"] == "PERMITTED"
    assert permitted["financing_state"] == "UNFUNDED", (
        "no financing trigger has fired, so the funding axis has not moved")


def test_funding_axis_commits_while_the_design_axis_stays_permitted(api):
    """PRD §3.5: "Committing the project to a scenario moves that scenario `ACTIVE →
    COMMITTED` and moves the project's funding axis from `PRE_QUALIFIED` to `COMMITTED`, or
    from `SHORTFALL` to `COMMITTED` when a homeowner has re-shopped the loan after a change
    order opened a gap."
    PRD §3.5: "Its `funding_gap_cents` must be exactly 0, or the commit is rejected with
    `ERR_FUNDING_GAP_OPEN` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/project_parallel_state_axes
    """
    ctx = setup_permitted_project(api)
    scenario = price_financing_scenario(api, ctx["project"]["id"],
                                        product_type="CONSTRUCTION_LOAN",
                                        appraisal_approach="INCOME_CAPITALIZATION")
    assert scenario["funding_gap_cents"] == 0

    committed = validate_success(api.commit_financing_scenario(scenario["id"], FINANCE_ADVISOR))

    assert committed["status"] == "COMMITTED"
    project = read_project(api, ctx["project"]["id"])
    assert project["financing_state"] == "COMMITTED"
    assert project["status"] == "PERMITTED", "the lifecycle axis is untouched by a commit"


def test_second_scenario_supersedes_the_first_and_bumps_the_project(api):
    """PRD §3.5: "Creating a scenario supersedes whatever came before it: any scenario of the
    same project still in `ACTIVE` moves to `SUPERSEDED`, and the new row is created in
    `ACTIVE` with every derived field stamped. If the project's `financing_state` was
    `UNFUNDED`, it advances to `PRE_QUALIFIED`; from `PRE_QUALIFIED`, `COMMITTED`, or
    `SHORTFALL` the funding axis is left exactly where it was, because pricing another option
    is not itself a funding event. Either way the project's `version` rises by 1."
    PRD §3.5: "Scenario listings for a project may be narrowed by `status` and by
    `appraisal_approach`."

    Design: Corner/cross_cutting_complexity_layers/financing_scenario_create_supersedes_prior_and_bumps_project_version
    """
    ctx = setup_intake_project(api)
    assert ctx["project"]["version"] == 1

    first = price_financing_scenario(api, ctx["project"]["id"], product_type="HELOC",
                                     appraisal_approach="SALES_COMPARISON")
    assert current_project_version(api, ctx["project"]["id"]) == 2

    second = price_financing_scenario(api, ctx["project"]["id"],
                                      product_type="CONSTRUCTION_LOAN",
                                      appraisal_approach="INCOME_CAPITALIZATION")

    assert validate_success(api.get_financing_scenario(first["id"], FINANCE_ADVISOR))["status"] \
        == "SUPERSEDED"
    assert second["status"] == "ACTIVE"

    project = read_project(api, ctx["project"]["id"])
    assert project["version"] == 3
    assert project["financing_state"] == "PRE_QUALIFIED"

    rows, meta = validate_paginated(api.list_financing_scenarios(
        ctx["project"]["id"], FINANCE_ADVISOR, {"status": "ACTIVE"}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == second["id"]
