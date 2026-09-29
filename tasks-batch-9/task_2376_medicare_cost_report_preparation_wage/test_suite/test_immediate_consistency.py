"""Nothing lags its write: the reads taken straight after a mapping and straight
after a filing already agree with the body those calls returned."""

from test_helpers import (
    DEFAULT_CLOCK,
    assert_fte_equals,
    assert_gme_summary,
    assert_instant_equals,
    assert_money_equals,
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
    create_resident,
    create_rotation,
    new_scenario,
    read_cost_center,
    read_cost_report,
    run_stepdown,
    setup_two_center_report,
)


def test_the_reads_taken_straight_after_a_mapping_already_agree_with_it(api):
    """The mapping response, the center read, the report read and the center's own
    ledger collection are consistent on the first attempt, with no write between.

    PRD 3.3: "An unmapped line can be mapped later through a dedicated mapping action that carries a `cost_center_id` in its payload and advances the line from `UNMAPPED` to `MAPPED`; mapping a line that is already `MAPPED` is an `ERR_INVALID_STATE_TRANSITION`."

    PRD 3.3: "For each cost center of the report, `direct_cost_cents` becomes the sum of `amount_cents` over the report's trial balance lines whose `mapped_cost_center_id` is that center and whose `status` is `MAPPED`."

    PRD 3.3: "The report's `total_direct_cost_cents` becomes the sum of `direct_cost_cents` across all its cost centers, and the report's `unmapped_tb_total_cents` becomes the sum of `amount_cents` over the report's lines whose `status` is `UNMAPPED`."

    Design: Corner/consistency model/the_map_response_and_the_immediately_following_reads_agree
    """
    scenario = new_scenario(api)
    add_cost_center(api, scenario, "cc_ag", {**CENTER_AG, "statistics": {"SQUARE_FEET": 0}})
    add_cost_center(
        api, scenario, "cc_routine", {**CENTER_ROUTINE, "statistics": {"SQUARE_FEET": 3000}}
    )
    add_mapped_tb_line(
        api, scenario, "6000", "Administration salaries", 100000000, "cc_ag"
    )
    nursing = add_unmapped_tb_line(
        api,
        scenario,
        gl_account="6200",
        description="Nursing salaries",
        amount_cents=200000000,
    )

    mapped = validate_success(
        api.map_trial_balance_line(
            nursing["id"],
            {"cost_center_id": scenario["cc_routine"]},
            scenario["analyst"],
        )
    )

    assert mapped["status"] == "MAPPED"
    assert mapped["mapped_cost_center_id"] == scenario["cc_routine"]

    assert_money_equals(
        read_cost_center(api, scenario, scenario["cc_routine"])["direct_cost_cents"],
        200000000,
        "03000 direct_cost_cents",
    )

    report = read_cost_report(api, scenario)
    assert_money_equals(report["unmapped_tb_total_cents"], 0, "unmapped_tb_total_cents")
    assert_money_equals(
        report["total_direct_cost_cents"], 300000000, "total_direct_cost_cents"
    )
    assert report["allocation_status"] == "NOT_RUN"

    lines, meta = validate_paginated(
        api.list_cost_center_trial_balance_lines(
            scenario["cc_routine"], scenario["analyst"]
        )
    )
    assert meta["total_count"] == 1
    assert len(lines) == 1
    assert lines[0]["gl_account"] == "6200"


def test_the_filing_body_already_carries_what_the_two_reads_return(api):
    """Filing stamps the clock and recomputes the resident counts inside the one
    request, and the computed summary read recomputes to the same 0.08.

    PRD 3.1: "Either filing recomputes the graduate medical education totals described in §3.6 and increments the report's `version`."

    PRD 3.1: "The first successful filing stamps `filed_at` from the logical clock; every successful filing after the first increments `amendment_count` by one."

    PRD 3.6: "These figures are recomputed whenever a rotation assignment is created, whenever one is voided, whenever the report is filed, and whenever the GME summary is read."

    PRD 3.6: "A provider with no settled history therefore divides by 1 and its rolling average equals its own capped count."

    Design: Corner/consistency model/the_filing_response_body_already_carries_what_the_reads_return
    """
    scenario = setup_two_center_report(api)
    run_stepdown(api, scenario, "SINGLE_APPORTIONMENT")
    accept_wage_submission(api, scenario)
    add_ucc_data_set(api, scenario)
    create_resident(api, scenario, full_name="Dana Okafor MD", irp_status="WITHIN_IRP")
    rotation = create_rotation(
        api,
        scenario,
        start_date="2025-07-01",
        end_date="2025-08-01",
        fte_fraction=1.00,
    )

    filed = validate_success(
        api.file_cost_report(scenario["report_id"], scenario["manager"])
    )

    assert filed["status"] == "FILED"
    assert_instant_equals(filed["filed_at"], DEFAULT_CLOCK, "filed_at")
    assert filed["rolling_average_fte"] == 0.08

    report = read_cost_report(api, scenario)
    assert report["status"] == "FILED"
    assert_instant_equals(report["filed_at"], DEFAULT_CLOCK, "filed_at")
    assert report["rolling_average_fte"] == 0.08
    assert report["amendment_count"] == 0

    summary = validate_success(
        api.get_gme_summary(scenario["report_id"], scenario["manager"])
    )
    assert_gme_summary(summary)
    assert summary["period_days"] == 365
    assert_fte_equals(
        summary["unweighted_fte_days_total"], 31.0000, "unweighted_fte_days_total"
    )
    assert summary["rolling_average_fte"] == 0.08
    assert summary["prior_period_count"] == 0

    reread_rotation = validate_success(
        api.get_rotation_assignment(rotation["id"], scenario["analyst"])
    )
    assert reread_rotation["overlap_days"] == 31

    resident = validate_success(
        api.get_resident(scenario["resident_id"], scenario["analyst"])
    )
    assert_fte_equals(resident["assigned_fte_days"], 31.0000, "assigned_fte_days")
