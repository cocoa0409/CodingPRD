"""The overhead stepdown: single versus double apportionment, the pinned
rounding order of the distribution primitive, and the empty-receiver branch."""

from test_helpers import (
    assert_money_equals,
    assert_ratio_equals,
    assert_stepdown_run,
    find_allocation_line,
    validate_success,
)
from test_helpers.factories import stepdown_run_payload
from test_helpers.fixtures import (
    current_report_version,
    read_cost_center,
    read_cost_report,
    run_stepdown,
    setup_dietary_zero_statistic_report,
    setup_five_center_report,
    setup_five_center_report_with_single_run,
)


def test_single_apportionment_closes_overhead_in_one_pass(api):
    """A single apportionment run over the canonical five centers settles the
    report at 448666667 cents of allowable cost.

    PRD 3.4: "The report's `total_allowable_cost_cents` is then the sum of `allocated_total_cost_cents` over the cost centers whose `center_type` is `ROUTINE` or `ANCILLARY` only — nonreimbursable centers do receive allocations, and are deliberately excluded from this total."

    Design: Difficulty/dual_variant_calc/stepdown_single_vs_double_apportionment_divergence
    """
    scenario = setup_five_center_report_with_single_run(api)
    run = scenario["single_run"]

    assert_stepdown_run(run)
    assert run["method"] == "SINGLE_APPORTIONMENT"
    assert run["status"] == "COMPLETED"
    assert_money_equals(run["total_allocated_cents"], 156666667, "total_allocated_cents")

    report = read_cost_report(api, scenario)
    assert report["allocation_status"] == "CURRENT"
    assert_money_equals(
        report["total_allowable_cost_cents"], 448666667, "total_allowable_cost_cents"
    )
    assert_ratio_equals(report["cost_to_charge_ratio"], 1.121667, "cost_to_charge_ratio")

    ancillary = read_cost_center(api, scenario, scenario["cc_ancillary"])
    nonreimb = read_cost_center(api, scenario, scenario["cc_nonreimb"])
    routine = read_cost_center(api, scenario, scenario["cc_routine"])
    assert_money_equals(ancillary["allocated_total_cost_cents"], 164666667, "05000 total")
    assert_money_equals(nonreimb["allocated_total_cost_cents"], 21333333, "09000 total")
    assert_money_equals(routine["allocated_total_cost_cents"], 284000000, "03000 total")


def test_double_apportionment_diverges_from_single_on_identical_inputs(api):
    """Re-running the identical structure under double apportionment moves
    allowable cost by 380953 cents and demotes the superseded run.

    PRD 3.4: "Because pass one lets overhead pools cross-charge each other and pass two redistributes those cross-charges, identical inputs produce different per-center figures and a different report-level allowable cost under this variant than under single apportionment — the two are not related by any constant factor."

    Design: Difficulty/dual_variant_calc/stepdown_single_vs_double_apportionment_divergence
    """
    scenario = setup_five_center_report_with_single_run(api)
    single_run_id = scenario["single_run"]["id"]

    double_run = run_stepdown(api, scenario, "DOUBLE_APPORTIONMENT")
    assert double_run["status"] == "COMPLETED"
    assert double_run["method"] == "DOUBLE_APPORTIONMENT"
    assert_money_equals(
        double_run["total_allocated_cents"], 158571429, "total_allocated_cents"
    )
    assert_money_equals(
        double_run["residual_unallocated_cents"], 0, "residual_unallocated_cents"
    )

    superseded = validate_success(api.get_stepdown_run(single_run_id, scenario["analyst"]))
    assert superseded["status"] == "STALE"
    assert superseded["stale_reason"] == "SUPERSEDED_BY_NEWER_RUN"

    report = read_cost_report(api, scenario)
    assert_money_equals(
        report["total_allowable_cost_cents"], 449047620, "total_allowable_cost_cents"
    )
    assert report["total_allowable_cost_cents"] - 448666667 == 380953
    assert_ratio_equals(report["cost_to_charge_ratio"], 1.122619, "cost_to_charge_ratio")

    ancillary = read_cost_center(api, scenario, scenario["cc_ancillary"])
    nonreimb = read_cost_center(api, scenario, scenario["cc_nonreimb"])
    routine = read_cost_center(api, scenario, scenario["cc_routine"])
    assert_money_equals(ancillary["allocated_total_cost_cents"], 165047620, "05000 total")
    assert_money_equals(nonreimb["allocated_total_cost_cents"], 20952380, "09000 total")
    assert_money_equals(routine["allocated_total_cost_cents"], 284000000, "03000 total")
    assert (
        routine["allocated_total_cost_cents"]
        + ancillary["allocated_total_cost_cents"]
        + nonreimb["allocated_total_cost_cents"]
        == 470000000
    )


def test_leftover_cents_break_equal_fractions_by_created_at(api):
    """Two receivers losing the identical fractional part split the leftover
    cent by creation order, giving 7619048 and 7619047.

    PRD 3.4: "The eligible receivers are then ordered by the fractional part they lost — exact share minus provisional share — in descending order, with ties broken by `created_at` ascending, and one additional cent is given to each of the first *remainder* receivers in that order."

    Design: Difficulty/combinatorial_formula/stepdown_floor_then_remainder_rounding_order_with_created_at_tie_break
    """
    scenario = setup_five_center_report(api)
    run = run_stepdown(api, scenario, "DOUBLE_APPORTIONMENT")

    assert len(run["allocation_lines"]) == 12
    assert len([line for line in run["allocation_lines"] if line["pass"] == 1]) == 7
    assert len([line for line in run["allocation_lines"] if line["pass"] == 2]) == 5

    to_ancillary = find_allocation_line(
        run, scenario["cc_laundry"], scenario["cc_ancillary"], 1
    )
    to_nonreimb = find_allocation_line(
        run, scenario["cc_laundry"], scenario["cc_nonreimb"], 1
    )
    assert_money_equals(to_ancillary["amount_cents"], 7619048, "laundry to 05000")
    assert_money_equals(to_nonreimb["amount_cents"], 7619047, "laundry to 09000")

    to_ag = find_allocation_line(run, scenario["cc_ag"], scenario["cc_laundry"], 1)
    assert_money_equals(to_ag["amount_cents"], 16666667, "A&G to laundry")
    assert_money_equals(
        find_allocation_line(run, scenario["cc_ag"], scenario["cc_routine"], 1)[
            "amount_cents"
        ],
        50000000,
        "A&G to 03000",
    )
    assert_money_equals(
        find_allocation_line(run, scenario["cc_ag"], scenario["cc_ancillary"], 1)[
            "amount_cents"
        ],
        33333333,
        "A&G to 05000",
    )


def test_floor_then_spread_conserves_the_distributed_pool(api):
    """Every allocation line is whole cents and the twelve lines add up to the
    run's reported allocated total with no residual.

    PRD 3.4: "This ordering is normative: distribute, then round down per receiver, then spread the leftover cents."

    Design: Difficulty/combinatorial_formula/stepdown_floor_then_remainder_rounding_order_with_created_at_tie_break
    """
    scenario = setup_five_center_report(api)
    run = run_stepdown(api, scenario, "DOUBLE_APPORTIONMENT")

    for line in run["allocation_lines"]:
        assert isinstance(line["amount_cents"], int)

    assert_money_equals(
        find_allocation_line(run, scenario["cc_laundry"], scenario["cc_ag"], 1)[
            "amount_cents"
        ],
        1904762,
        "laundry to A&G",
    )
    assert_money_equals(
        find_allocation_line(run, scenario["cc_laundry"], scenario["cc_routine"], 1)[
            "amount_cents"
        ],
        22857143,
        "laundry to 03000 pass 1",
    )
    assert_money_equals(
        find_allocation_line(run, scenario["cc_ag"], scenario["cc_routine"], 2)[
            "amount_cents"
        ],
        1142857,
        "A&G to 03000 pass 2",
    )
    assert_money_equals(
        find_allocation_line(run, scenario["cc_ag"], scenario["cc_ancillary"], 2)[
            "amount_cents"
        ],
        761905,
        "A&G to 05000 pass 2",
    )
    assert_money_equals(
        find_allocation_line(run, scenario["cc_laundry"], scenario["cc_routine"], 2)[
            "amount_cents"
        ],
        10000000,
        "laundry to 03000 pass 2",
    )
    assert_money_equals(
        find_allocation_line(run, scenario["cc_laundry"], scenario["cc_ancillary"], 2)[
            "amount_cents"
        ],
        3333334,
        "laundry to 05000 pass 2",
    )
    assert_money_equals(
        find_allocation_line(run, scenario["cc_laundry"], scenario["cc_nonreimb"], 2)[
            "amount_cents"
        ],
        3333333,
        "laundry to 09000 pass 2",
    )

    line_total = sum(line["amount_cents"] for line in run["allocation_lines"])
    assert_money_equals(run["total_allocated_cents"], 158571429, "total_allocated_cents")
    assert line_total == run["total_allocated_cents"]
    assert_money_equals(run["residual_unallocated_cents"], 0, "residual")

    report = read_cost_report(api, scenario)
    assert_money_equals(
        report["total_allowable_cost_cents"], 449047620, "total_allowable_cost_cents"
    )


def test_allocator_with_no_eligible_receiver_keeps_its_pool_as_residual(api):
    """A dietary pool whose basis statistic nobody reports completes with zero
    allocation lines and its whole 60000000 cents left as residual.

    PRD 3.4: "If no receiver is eligible, no division is performed and the entire pool remains on the allocator as residual."

    Design: Difficulty/boundary_precision_check/stepdown_zero_statistic_basis_returns_residual_without_dividing
    """
    scenario = setup_dietary_zero_statistic_report(api)
    version = current_report_version(api, scenario)

    response = api.create_stepdown_run(
        scenario["report_id"],
        stepdown_run_payload(version, method="SINGLE_APPORTIONMENT"),
        scenario["analyst"],
    )
    run = validate_success(response, 201)

    assert run["status"] == "COMPLETED"
    assert run["allocation_lines"] == []
    assert_money_equals(run["total_allocated_cents"], 0, "total_allocated_cents")
    assert_money_equals(
        run["residual_unallocated_cents"], 60000000, "residual_unallocated_cents"
    )

    dietary = read_cost_center(api, scenario, scenario["cc_dietary"])
    assert_money_equals(dietary["allocated_out_cents"], 0, "dietary allocated_out_cents")
    assert_money_equals(
        dietary["allocated_total_cost_cents"], 60000000, "dietary allocated total"
    )


def test_stranded_overhead_is_excluded_from_allowable_cost(api):
    """The undistributed dietary cost stays on a general service center, so
    allowable cost reads 320000000 and the ratio 0.800000.

    PRD 3.4: "Finally the report's `cost_to_charge_ratio` becomes `total_allowable_cost_cents` divided by `total_charges_cents`, rounded half up to six decimal places, and is 0.000000 whenever `total_charges_cents` is 0."

    Design: Difficulty/boundary_precision_check/stepdown_zero_statistic_basis_returns_residual_without_dividing
    """
    scenario = setup_dietary_zero_statistic_report(api)
    run_stepdown(api, scenario, "SINGLE_APPORTIONMENT")

    routine = read_cost_center(api, scenario, scenario["cc_routine"])
    ancillary = read_cost_center(api, scenario, scenario["cc_ancillary"])
    assert_money_equals(routine["allocated_in_cents"], 0, "03000 allocated_in_cents")
    assert_money_equals(routine["allocated_total_cost_cents"], 200000000, "03000 total")
    assert_money_equals(ancillary["allocated_in_cents"], 0, "05000 allocated_in_cents")
    assert_money_equals(ancillary["allocated_total_cost_cents"], 120000000, "05000 total")

    report = read_cost_report(api, scenario)
    assert_money_equals(
        report["total_allowable_cost_cents"], 320000000, "total_allowable_cost_cents"
    )
    assert_ratio_equals(report["cost_to_charge_ratio"], 0.800000, "cost_to_charge_ratio")
    assert report["allocation_status"] == "CURRENT"
