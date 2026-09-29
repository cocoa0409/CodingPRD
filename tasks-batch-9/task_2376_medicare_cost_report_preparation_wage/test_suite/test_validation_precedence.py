"""Requests that violate two rules at once resolve on the lower priority band."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    ApiErrorId,
    assert_money_equals,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import (
    general_service_center_payload,
    reclassification_payload,
    workpaper_leg,
)
from test_helpers.fixtures import (
    CENTER_ROUTINE,
    add_cost_center,
    add_unmapped_tb_line,
    create_cost_report,
    new_scenario,
    read_cost_center,
    read_cost_report,
    set_clock,
    setup_two_center_report,
)


def _two_reports_one_provider(api):
    scenario = new_scenario(api)
    add_cost_center(api, scenario, "cc_ag", general_service_center_payload())
    add_cost_center(api, scenario, "cc_routine", dict(CENTER_ROUTINE, statistics={"SQUARE_FEET": 3000}))

    report_b = create_cost_report(
        api,
        scenario["provider_id"],
        fiscal_year_begin="2024-07-01",
        fiscal_year_end="2025-06-30",
        total_charges_cents=380000000,
        medicare_discharges=480,
    )
    center_b = get_success_data(
        api.create_cost_center(
            report_b["id"], general_service_center_payload(), scenario["analyst"]
        )
    )
    scenario["report_b_id"] = report_b["id"]
    scenario["cc_b_ag"] = center_b["id"]
    return scenario


def test_foreign_leg_is_reported_before_the_net_zero_arithmetic(api):
    """A reclassification whose second leg belongs to another report fails on the
    ownership rule, not on the fact that its legs sum to 5000000.

    PRD 3.3: "Each element of `legs` is an object pairing a `cost_center_id` with an `amount_cents` figure, and every named cost center must belong to the same cost report as the entry; a leg pointing at a foreign center is rejected with `ERR_COST_CENTER_FOREIGN_TO_REPORT`."

    Design: Difficulty/priority_pair_validation_conflict/foreign_cost_center_leg_outranks_unbalanced_reclassification
    """
    scenario = _two_reports_one_provider(api)

    response = api.create_workpaper_entry(
        scenario["report_id"],
        reclassification_payload(
            [
                workpaper_leg(scenario["cc_ag"], -10000000),
                workpaper_leg(scenario["cc_b_ag"], 15000000),
            ],
            code="A6-1",
            description="Reclassify administration to nursing",
        ),
        scenario["analyst"],
    )

    validate_error(response, ApiErrorId.ERR_COST_CENTER_FOREIGN_TO_REPORT.value, 422)
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_RECLASS_NOT_BALANCED.value
    )


def test_rejected_reclassification_writes_nothing_at_all(api):
    """Because the first violated rule decides the response, no entry is stored
    and no cost center figure moves.

    PRD 2.10: "All validation on a request is evaluated in a strict ascending priority order, and **the first violated rule decides the response; nothing is written**."

    Design: Difficulty/priority_pair_validation_conflict/foreign_cost_center_leg_outranks_unbalanced_reclassification
    """
    scenario = _two_reports_one_provider(api)

    api.create_workpaper_entry(
        scenario["report_id"],
        reclassification_payload(
            [
                workpaper_leg(scenario["cc_ag"], -10000000),
                workpaper_leg(scenario["cc_b_ag"], 15000000),
            ],
            code="A6-1",
            description="Reclassify administration to nursing",
        ),
        scenario["analyst"],
    )

    entries, meta = validate_paginated(
        api.list_report_workpaper_entries(scenario["report_id"], scenario["analyst"])
    )
    assert meta["total_count"] == 0
    assert entries == []

    ag = read_cost_center(api, scenario, scenario["cc_ag"])
    assert_money_equals(ag["reclassified_amount_cents"], 0, "reclassified_amount_cents")
    assert_money_equals(
        ag["post_reclass_direct_cost_cents"], 0, "post_reclass_direct_cost_cents"
    )

    foreign = read_cost_center(api, scenario, scenario["cc_b_ag"])
    assert_money_equals(
        foreign["reclassified_amount_cents"], 0, "foreign reclassified_amount_cents"
    )
    assert read_cost_report(api, scenario)["allocation_status"] == "NOT_RUN"


def _report_past_its_deadline(api):
    scenario = setup_two_center_report(api)
    add_unmapped_tb_line(
        api, scenario, "6900", "Unassigned suspense account", 1000000
    )
    set_clock(api, "2026-12-01T00:00:00Z")
    return scenario


def test_expired_filing_deadline_outranks_the_readiness_preconditions(api):
    """Filing one day late reports the deadline, even though the ledger is
    unmapped and no allocation has run.

    PRD 3.1: "The two paths differ in exactly one respect: the `DRAFT` filing additionally requires that the logical clock's date fall on or before `filing_deadline`, and a later date is rejected with `ERR_FILING_DEADLINE_PASSED`; the amended filing out of `REOPENED` skips the deadline test entirely, because a reopening granted years after the fact could never satisfy the original calendar."

    Design: Difficulty/priority_pair_validation_conflict/filing_deadline_outranks_unmapped_trial_balance_on_file
    """
    scenario = _report_past_its_deadline(api)

    response = api.file_cost_report(scenario["report_id"], scenario["manager"])

    validate_error(response, ApiErrorId.ERR_FILING_DEADLINE_PASSED.value, 422)
    error_id = response.json()["data"]["error_id"]
    assert error_id != ApiErrorId.ERR_UNMAPPED_TRIAL_BALANCE.value
    assert error_id != ApiErrorId.ERR_ALLOCATION_NOT_CURRENT.value


def test_late_filing_attempt_leaves_the_report_and_its_ledger_untouched(api):
    """The deadline computed from the fiscal year end holds at 2026-11-30 and the
    rejected filing leaves the report in DRAFT with its orphan line unmapped.

    PRD 3.1: "The deadline is the fiscal year end advanced by five calendar months, clamped to the last day of the target month when the source day-of-month does not exist there."

    Design: Difficulty/priority_pair_validation_conflict/filing_deadline_outranks_unmapped_trial_balance_on_file
    """
    scenario = _report_past_its_deadline(api)
    orphan_id = scenario["unmapped_line"]["id"]

    api.file_cost_report(scenario["report_id"], scenario["manager"])

    report = read_cost_report(api, scenario)
    assert report["filing_deadline"] == "2026-11-30"
    assert_money_equals(
        report["unmapped_tb_total_cents"], 1000000, "unmapped_tb_total_cents"
    )
    assert report["allocation_status"] == "NOT_RUN"
    assert report["status"] == "DRAFT"
    assert report["filed_at"] is None

    line = get_success_data(api.get_trial_balance_line(orphan_id, scenario["analyst"]))
    assert line["status"] == "UNMAPPED"
    assert line["mapped_cost_center_id"] is None
