"""Named calculations: the allocation primitive on the smallest structure, the
ledger rollup's input filter, the wage-related cost cap, per-category rounding,
and the two settlement variants."""

from test_helpers import (
    ApiErrorId,
    assert_money_equals,
    assert_ratio_equals,
    assert_settlement,
    assert_stepdown_run,
    assert_trial_balance_line,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    CENTER_AG,
    CENTER_ROUTINE,
    accept_wage_submission,
    add_cost_center,
    add_mapped_tb_line,
    add_ucc_data_set,
    add_unmapped_tb_line,
    create_settlement,
    file_report,
    new_scenario,
    read_cost_center,
    read_cost_report,
    run_stepdown,
    setup_two_center_report,
)

MINIMAL_SURVEY_INPUTS = {
    "total_salaries_cents": 5000000000,
    "total_paid_hours": 2000000.00,
}


def _tentative_settlement_on_a_single_apportionment_basis(api):
    """A two-center report filed and tentatively settled off a single pass."""
    scenario = setup_two_center_report(api)
    run_stepdown(api, scenario, "SINGLE_APPORTIONMENT")
    accept_wage_submission(api, scenario)
    add_ucc_data_set(api, scenario)
    file_report(api, scenario)
    create_settlement(api, scenario, "TENTATIVE")
    return scenario


def test_one_allocator_closes_its_whole_pool_into_the_single_receiver(api):
    """The only eligible receiver takes the entire 100000000 pool in one pass-1
    line, leaving no residual and a 0.750000 cost-to-charge ratio.

    PRD 3.4: "Each cost center's `allocated_in_cents` becomes the sum of `amount_cents` over allocation lines whose `to_cost_center_id` is that center, its `allocated_out_cents` becomes the sum over lines whose `from_cost_center_id` is that center, and its `allocated_total_cost_cents` becomes `post_adjustment_cost_cents` plus `allocated_in_cents` minus `allocated_out_cents`."

    PRD 3.4: "Finally the report's `cost_to_charge_ratio` becomes `total_allowable_cost_cents` divided by `total_charges_cents`, rounded half up to six decimal places, and is 0.000000 whenever `total_charges_cents` is 0."

    Design: Corner/calculations/stepdown_allocation_distributes_general_service_cost_by_square_feet
    """
    scenario = setup_two_center_report(api)

    run = run_stepdown(api, scenario, "SINGLE_APPORTIONMENT")

    assert_stepdown_run(run)
    assert run["status"] == "COMPLETED"
    assert run["method"] == "SINGLE_APPORTIONMENT"
    assert len(run["allocation_lines"]) == 1
    line = run["allocation_lines"][0]
    assert line["pass"] == 1
    assert line["from_cost_center_id"] == scenario["cc_ag"]
    assert line["to_cost_center_id"] == scenario["cc_routine"]
    assert_money_equals(line["amount_cents"], 100000000, "allocation line amount_cents")
    assert_money_equals(run["total_allocated_cents"], 100000000, "total_allocated_cents")
    assert_money_equals(
        run["residual_unallocated_cents"], 0, "residual_unallocated_cents"
    )
    assert run["failure_reason"] is None
    assert run["stale_reason"] is None

    allocator = read_cost_center(api, scenario, scenario["cc_ag"])
    assert_money_equals(allocator["allocated_in_cents"], 0, "00100 allocated_in_cents")
    assert_money_equals(
        allocator["allocated_out_cents"], 100000000, "00100 allocated_out_cents"
    )
    assert_money_equals(
        allocator["allocated_total_cost_cents"], 0, "00100 allocated_total_cost_cents"
    )

    receiver = read_cost_center(api, scenario, scenario["cc_routine"])
    assert_money_equals(
        receiver["allocated_in_cents"], 100000000, "03000 allocated_in_cents"
    )
    assert_money_equals(receiver["allocated_out_cents"], 0, "03000 allocated_out_cents")
    assert_money_equals(
        receiver["allocated_total_cost_cents"],
        300000000,
        "03000 allocated_total_cost_cents",
    )

    report = read_cost_report(api, scenario)
    assert_money_equals(
        report["total_allowable_cost_cents"], 300000000, "total_allowable_cost_cents"
    )
    assert_ratio_equals(report["cost_to_charge_ratio"], 0.750000, "cost_to_charge_ratio")
    assert report["allocation_status"] == "CURRENT"


def test_an_unmapped_ledger_line_feeds_only_the_unmapped_total(api):
    """A line loaded without a cost center lands UNMAPPED and puts its 200000000
    into the report's unmapped total, not into any center's direct cost.

    PRD 3.3: "The report's `total_direct_cost_cents` becomes the sum of `direct_cost_cents` across all its cost centers, and the report's `unmapped_tb_total_cents` becomes the sum of `amount_cents` over the report's lines whose `status` is `UNMAPPED`."

    PRD 3.3: "The line's `status` is set accordingly: `MAPPED` when a cost center was supplied and `UNMAPPED` when it was not."

    Design: Corner/calculations/unmapped_trial_balance_lines_are_excluded_from_direct_cost
    """
    scenario = new_scenario(api)
    add_cost_center(api, scenario, "cc_ag", {**CENTER_AG, "statistics": {"SQUARE_FEET": 0}})
    add_cost_center(
        api, scenario, "cc_routine", {**CENTER_ROUTINE, "statistics": {"SQUARE_FEET": 3000}}
    )
    add_mapped_tb_line(
        api, scenario, "6000", "Administration salaries", 100000000, "cc_ag"
    )

    unmapped = add_unmapped_tb_line(
        api,
        scenario,
        gl_account="6200",
        description="Nursing salaries awaiting mapping",
        amount_cents=200000000,
    )

    assert_trial_balance_line(unmapped)
    assert unmapped["status"] == "UNMAPPED"
    assert unmapped["mapped_cost_center_id"] is None

    assert_money_equals(
        read_cost_center(api, scenario, scenario["cc_ag"])["direct_cost_cents"],
        100000000,
        "00100 direct_cost_cents",
    )
    assert_money_equals(
        read_cost_center(api, scenario, scenario["cc_routine"])["direct_cost_cents"],
        0,
        "03000 direct_cost_cents",
    )

    report = read_cost_report(api, scenario)
    assert_money_equals(
        report["total_direct_cost_cents"], 100000000, "total_direct_cost_cents"
    )
    assert_money_equals(
        report["unmapped_tb_total_cents"], 200000000, "unmapped_tb_total_cents"
    )

    _lines, unmapped_meta = validate_paginated(
        api.list_report_trial_balance_lines(
            scenario["report_id"], scenario["analyst"], {"status": "UNMAPPED"}
        )
    )
    assert unmapped_meta["total_count"] == 1

    _receiver_lines, receiver_meta = validate_paginated(
        api.list_cost_center_trial_balance_lines(
            scenario["cc_routine"], scenario["analyst"]
        )
    )
    assert receiver_meta["total_count"] == 0


def test_claimed_wage_related_costs_are_trimmed_to_a_quarter_of_salaries(api):
    """A claimed 1500000000 is trimmed to the 1250000000 cap, so the pooled wage
    settles at 3125 cents rather than the 3250 an uncapped numerator would give.

    PRD 3.5: "First, `allowed_wage_related_costs_cents` is the lesser of `wage_related_costs_cents` and one quarter of `total_salaries_cents` rounded down to a whole cent — the wage-related cost cap is 25 percent of total salaries, and it floors rather than rounds."

    Design: Corner/calculations/wage_related_costs_are_capped_at_twenty_five_percent_of_salaries
    """
    scenario = new_scenario(api)
    submission = validate_success(
        api.create_wage_index_submission(
            scenario["report_id"], dict(MINIMAL_SURVEY_INPUTS), scenario["analyst"]
        ),
        201,
    )

    corrected = validate_success(
        api.update_wage_index_submission(
            submission["id"],
            {"wage_related_costs_cents": 1500000000},
            scenario["analyst"],
        )
    )

    assert_money_equals(
        corrected["wage_related_costs_cents"], 1500000000, "wage_related_costs_cents"
    )
    assert_money_equals(
        corrected["allowed_wage_related_costs_cents"],
        1250000000,
        "allowed_wage_related_costs_cents",
    )
    assert_money_equals(corrected["unadjusted_ahw_cents"], 3125, "unadjusted_ahw_cents")
    assert corrected["unadjusted_ahw_cents"] != 3250
    assert_money_equals(corrected["effective_ahw_cents"], 3125, "effective_ahw_cents")
    assert corrected["occ_mix_adjusted_ahw_cents"] is None
    assert corrected["status"] == "DRAFT"


def test_a_category_wage_of_exactly_half_a_cent_rounds_up(api):
    """15001 cents over 2.00 hours is exactly 7500.5, and half up stores 7501; one
    staffed category is too few to weight, so the pooled 2500 prevails.

    PRD 3.5: "The server computes that response's `category_ahw_cents` as `reported_salaries_cents` divided by `reported_hours`, rounded half up to a whole cent, leaving it null when `reported_hours` is 0."

    PRD 3.5: "`effective_ahw_cents` resolves the choice: it is `occ_mix_adjusted_ahw_cents` when `occ_mix_category_count` is at least 3, and `unadjusted_ahw_cents` otherwise."

    Design: Corner/calculations/category_hourly_wage_rounds_half_up_to_whole_cents
    """
    scenario = new_scenario(api)
    submission = validate_success(
        api.create_wage_index_submission(
            scenario["report_id"], dict(MINIMAL_SURVEY_INPUTS), scenario["analyst"]
        ),
        201,
    )

    response = validate_success(
        api.create_occ_mix_response(
            submission["id"],
            {"category": "RN", "reported_hours": 2.00, "reported_salaries_cents": 15001},
            scenario["analyst"],
        ),
        201,
    )

    assert response["category"] == "RN"
    assert_money_equals(response["category_ahw_cents"], 7501, "category_ahw_cents")
    assert response["category_ahw_cents"] != 7500

    reread = validate_success(
        api.get_wage_index_submission(submission["id"], scenario["analyst"])
    )
    assert reread["occ_mix_category_count"] == 1
    assert reread["reported_hours_total"] == 2.00
    assert reread["occ_mix_adjusted_ahw_cents"] is None
    assert_money_equals(reread["unadjusted_ahw_cents"], 2500, "unadjusted_ahw_cents")
    assert_money_equals(reread["effective_ahw_cents"], 2500, "effective_ahw_cents")


def test_the_final_settlement_credits_back_the_tentative_advance(api):
    """The final settlement pays 32300000: the whole net plus uncompensated care,
    less the 75000000 the tentative stage already advanced.

    PRD 3.8: "For a `TENTATIVE` settlement, `ucc_payment_cents` is 0 — the tentative stage ignores uncompensated care entirely — and `prior_tentative_paid_cents` is 0, and `amount_due_provider_cents` is three quarters of the difference between `reimbursable_cost_cents` and the report's `interim_payments_received_cents`, rounded half up to a whole cent."

    PRD 3.8: "Then `amount_due_provider_cents` is the difference between `reimbursable_cost_cents` and `interim_payments_received_cents`, plus `ucc_payment_cents`, minus `prior_tentative_paid_cents`."

    Design: Corner/calculations/final_settlement_subtracts_the_prior_tentative_payment
    """
    scenario = _tentative_settlement_on_a_single_apportionment_basis(api)
    tentative = scenario["tentative_settlement"]
    assert_settlement(tentative)
    assert tentative["stage"] == "TENTATIVE"
    assert tentative["basis_method"] == "SINGLE_APPORTIONMENT"
    assert_money_equals(
        tentative["basis_allowable_cost_cents"], 300000000, "basis_allowable_cost_cents"
    )
    assert_money_equals(
        tentative["reimbursable_cost_cents"], 120000000, "reimbursable_cost_cents"
    )
    assert_money_equals(tentative["ucc_payment_cents"], 0, "tentative ucc_payment_cents")
    assert_money_equals(
        tentative["prior_tentative_paid_cents"], 0, "prior_tentative_paid_cents"
    )
    assert_money_equals(
        tentative["amount_due_provider_cents"], 75000000, "amount_due_provider_cents"
    )

    run_stepdown(api, scenario, "DOUBLE_APPORTIONMENT")
    final = create_settlement(api, scenario, "FINAL")

    assert final["stage"] == "FINAL"
    assert final["basis_method"] == "DOUBLE_APPORTIONMENT"
    assert_money_equals(
        final["basis_allowable_cost_cents"], 300000000, "basis_allowable_cost_cents"
    )
    assert_money_equals(
        final["reimbursable_cost_cents"], 120000000, "reimbursable_cost_cents"
    )
    assert_money_equals(final["ucc_payment_cents"], 7300000, "final ucc_payment_cents")
    assert_money_equals(
        final["prior_tentative_paid_cents"], 75000000, "prior_tentative_paid_cents"
    )
    assert_money_equals(
        final["amount_due_provider_cents"], 32300000, "amount_due_provider_cents"
    )

    ucc = validate_success(
        api.get_ucc_data_set(scenario["ucc_data_set_id"], scenario["analyst"])
    )
    assert_money_equals(
        ucc["uncompensated_care_cost_cents"], 36500000, "uncompensated_care_cost_cents"
    )
    assert_money_equals(ucc["ucc_payment_cents"], 7300000, "ucc_payment_cents")

    report = read_cost_report(api, scenario)
    assert report["status"] == "FINAL_SETTLED"
    assert_money_equals(
        report["allowable_cost_per_discharge_cents"],
        600000,
        "allowable_cost_per_discharge_cents",
    )


def test_a_single_pass_allocation_cannot_carry_the_final_settlement(api):
    """The tentative stage accepted the single-pass basis; the final stage refuses
    it and the report stays tentatively settled.

    PRD 3.8: "The `TENTATIVE_SETTLED` path to `FINAL_SETTLED` demands three further things: that a settlement with `stage` `TENTATIVE` and `status` `ISSUED` exist; that the report's `COMPLETED` stepdown run have `method` `DOUBLE_APPORTIONMENT`, since a single-pass allocation is not an acceptable basis for a final settlement and a request made against one is rejected with `ERR_FINAL_REQUIRES_DOUBLE_APPORTIONMENT`; and that no audit adjustment of the tentative settlement remain in `PROPOSED`, `ACCEPTED_BY_PROVIDER` or `PROTESTED`, else `ERR_AUDIT_ADJUSTMENT_UNRESOLVED`."

    Design: Corner/calculations/final_settlement_requires_a_double_apportionment_basis_run
    """
    scenario = _tentative_settlement_on_a_single_apportionment_basis(api)

    response = api.create_settlement(
        scenario["report_id"], {"stage": "FINAL"}, scenario["auditor"]
    )

    validate_error(
        response, ApiErrorId.ERR_FINAL_REQUIRES_DOUBLE_APPORTIONMENT.value, 422
    )

    report = read_cost_report(api, scenario)
    assert report["status"] == "TENTATIVE_SETTLED"
    assert_money_equals(
        report["allowable_cost_per_discharge_cents"],
        0,
        "allowable_cost_per_discharge_cents",
    )

    settlements, meta = validate_paginated(
        api.list_report_settlements(scenario["report_id"], scenario["auditor"])
    )
    assert meta["total_count"] == 1
    assert len(settlements) == 1
    assert_money_equals(
        settlements[0]["amount_due_provider_cents"],
        75000000,
        "amount_due_provider_cents",
    )
