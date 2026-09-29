"""Transitions refused because of the state of a neighbouring entity."""

from test_helpers import (
    ApiErrorId,
    assert_money_equals,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import appeal_case_payload
from test_helpers.fixtures import (
    add_ucc_data_set,
    add_wage_submission,
    read_cost_report,
    run_stepdown,
    setup_tentative_settlement,
    setup_two_center_report,
    submit_wage_submission,
)


def _report_ready_except_for_the_wage_review(api):
    scenario = setup_two_center_report(api)
    run_stepdown(api, scenario, "SINGLE_APPORTIONMENT")
    add_wage_submission(api, scenario)
    submit_wage_submission(api, scenario)
    add_ucc_data_set(api, scenario)
    return scenario


def test_filing_waits_for_the_contractor_to_accept_the_wage_data(api):
    """A merely submitted wage survey is not an accepted one, so the filing is
    refused on the wage precondition.

    PRD 3.1: "Its wage index submission must have reached `ACCEPTED`, equivalently `wage_data_status` must read `VERIFIED`, else `ERR_WAGE_SUBMISSION_NOT_ACCEPTED`."

    Design: Difficulty/cross_entity_state_dependency/cost_report_cannot_be_filed_until_wage_submission_is_accepted
    """
    scenario = _report_ready_except_for_the_wage_review(api)

    response = api.file_cost_report(scenario["report_id"], scenario["manager"])

    validate_error(response, ApiErrorId.ERR_WAGE_SUBMISSION_NOT_ACCEPTED.value, 422)

    submission = validate_success(
        api.get_wage_index_submission(scenario["submission_id"], scenario["analyst"])
    )
    assert submission["status"] == "SUBMITTED"

    report = read_cost_report(api, scenario)
    assert report["wage_data_status"] == "COLLECTED"
    assert report["status"] == "DRAFT"
    assert report["filed_at"] is None


def test_the_reports_own_readiness_conditions_are_all_satisfied(api):
    """The refusal comes only from the neighbouring submission: the ledger, the
    allocation, the deadline and the uncompensated care data all check out.

    PRD 3.1: "Both paths demand the same four readiness conditions. The report's `unmapped_tb_total_cents` must be exactly 0, else `ERR_UNMAPPED_TRIAL_BALANCE`."

    Design: Difficulty/cross_entity_state_dependency/cost_report_cannot_be_filed_until_wage_submission_is_accepted
    """
    scenario = _report_ready_except_for_the_wage_review(api)

    api.file_cost_report(scenario["report_id"], scenario["manager"])

    report = read_cost_report(api, scenario)
    assert_money_equals(report["unmapped_tb_total_cents"], 0, "unmapped_tb_total_cents")
    assert report["allocation_status"] == "CURRENT"
    assert report["filing_deadline"] == "2026-11-30"
    assert_money_equals(
        report["total_allowable_cost_cents"], 300000000, "total_allowable_cost_cents"
    )

    ucc = validate_success(
        api.get_ucc_data_set(scenario["ucc_data_set_id"], scenario["analyst"])
    )
    assert ucc["dsh_eligible"] is True


def test_reopening_needs_a_final_settlement_not_a_tentative_one(api):
    """A reopening request naming the tentative settlement is refused on the
    stage, not on ownership.

    PRD 3.9: "The named settlement must belong to the same cost report as the case, else `ERR_SETTLEMENT_FOREIGN_TO_REPORT`, and must have `stage` `FINAL`, else `ERR_SETTLEMENT_STAGE_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/appeal_case_cannot_be_opened_against_a_tentative_settlement
    """
    scenario = setup_tentative_settlement(api)

    response = api.create_appeal_case(
        scenario["report_id"],
        appeal_case_payload(
            scenario["tentative_settlement_id"],
            kind="REOPENING",
            issue_description="Reopen to correct the operating room allocation statistic",
            amount_at_issue_cents=2500000,
        ),
        scenario["manager"],
    )

    validate_error(response, ApiErrorId.ERR_SETTLEMENT_STAGE_INVALID.value, 422)
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_SETTLEMENT_FOREIGN_TO_REPORT.value
    )


def test_refused_reopening_leaves_the_tentative_settlement_as_issued(api):
    """No case row is created and the settlement that was named keeps its
    tentative stage and issued status.

    PRD 3.8: "Issuing the tentative settlement advances the report from `FILED` to `TENTATIVE_SETTLED`, and additionally requires that no settlement of this report with `stage` `TENTATIVE` and `status` `ISSUED` already exist."

    Design: Difficulty/cross_entity_state_dependency/appeal_case_cannot_be_opened_against_a_tentative_settlement
    """
    scenario = setup_tentative_settlement(api)

    api.create_appeal_case(
        scenario["report_id"],
        appeal_case_payload(
            scenario["tentative_settlement_id"],
            kind="REOPENING",
            issue_description="Reopen to correct the operating room allocation statistic",
            amount_at_issue_cents=2500000,
        ),
        scenario["manager"],
    )

    settlement = validate_success(
        api.get_settlement(scenario["tentative_settlement_id"], scenario["auditor"])
    )
    assert settlement["stage"] == "TENTATIVE"
    assert settlement["status"] == "ISSUED"

    cases, meta = validate_paginated(
        api.list_appeal_cases(
            scenario["manager"], {"cost_report_id": scenario["report_id"]}
        )
    )
    assert meta["total_count"] == 0
    assert cases == []

    report = read_cost_report(api, scenario)
    assert report["status"] == "TENTATIVE_SETTLED"
    assert report["amendment_count"] == 0
