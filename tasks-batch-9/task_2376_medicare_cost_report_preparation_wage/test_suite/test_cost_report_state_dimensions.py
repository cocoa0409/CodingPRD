"""The cost report's status axis and its wage data axis advance independently."""

from test_helpers import DEFAULT_CLOCK, assert_instant_equals, assert_money_equals
from test_helpers.fixtures import (
    accept_wage_submission,
    add_ucc_data_set,
    file_report,
    read_cost_report,
    record_wage_review_decision,
    run_stepdown,
    setup_two_center_report,
    start_wage_review,
    submit_wage_submission,
)


def _filed_two_center_report(api):
    scenario = setup_two_center_report(api)
    run_stepdown(api, scenario, "SINGLE_APPORTIONMENT")
    accept_wage_submission(api, scenario)
    add_ucc_data_set(api, scenario)
    report = file_report(api, scenario)
    assert report["status"] == "FILED"
    assert report["wage_data_status"] == "VERIFIED"
    return scenario


def test_reopened_desk_review_leaves_a_filed_report_filed(api):
    """A filed report whose wage data goes back under review keeps status FILED
    through the whole reopened cycle, including REVISION_REQUESTED.

    PRD 2.6: "The two dimensions interleave freely: a report may already be `FILED` on the `status` axis while a later desk review pushes `wage_data_status` back to `UNDER_REVIEW` and then to `REVISION_REQUESTED`."

    Design: Difficulty/non_linear_state_machine/cost_report_status_and_wage_data_status_evolve_independently
    """
    scenario = _filed_two_center_report(api)

    start_wage_review(api, scenario)
    report = read_cost_report(api, scenario)
    assert report["wage_data_status"] == "UNDER_REVIEW"
    assert report["status"] == "FILED"

    changed = record_wage_review_decision(
        api, scenario, "REQUEST_CHANGE", "Reconcile paid hours to the payroll register"
    )
    assert changed["status"] == "CHANGE_REQUESTED"
    report = read_cost_report(api, scenario)
    assert report["wage_data_status"] == "REVISION_REQUESTED"
    assert report["status"] == "FILED"

    resubmitted = submit_wage_submission(api, scenario)
    assert resubmitted["revision_number"] == 1
    report = read_cost_report(api, scenario)
    assert report["wage_data_status"] == "COLLECTED"
    assert report["status"] == "FILED"


def test_wage_axis_movement_touches_neither_filed_at_nor_the_allocation(api):
    """Walking the wage axis through three transitions leaves filed_at, the
    amendment count, the allocation freshness and allowable cost untouched.

    PRD 3.5: "`REQUEST_CHANGE` advances the submission to `CHANGE_REQUESTED` with no additional precondition; it sets `review_note`, sets the report's `wage_data_status` to `REVISION_REQUESTED` while leaving the report's `status` untouched, and increments the report's `version`."

    Design: Difficulty/non_linear_state_machine/cost_report_status_and_wage_data_status_evolve_independently
    """
    scenario = _filed_two_center_report(api)

    def check_untouched(report):
        assert_instant_equals(report["filed_at"], DEFAULT_CLOCK, "filed_at")
        assert report["amendment_count"] == 0
        assert report["allocation_status"] == "CURRENT"
        assert_money_equals(
            report["total_allowable_cost_cents"], 300000000, "total_allowable_cost_cents"
        )

    check_untouched(read_cost_report(api, scenario))

    start_wage_review(api, scenario)
    check_untouched(read_cost_report(api, scenario))

    record_wage_review_decision(
        api, scenario, "REQUEST_CHANGE", "Reconcile paid hours to the payroll register"
    )
    check_untouched(read_cost_report(api, scenario))

    submit_wage_submission(api, scenario)
    check_untouched(read_cost_report(api, scenario))
