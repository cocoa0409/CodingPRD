"""Declared transitions, their side effects, and the refusals that guard the
states from which a transition does not exist."""

from test_helpers import (
    CANONICAL_OCC_MIX,
    DEFAULT_CLOCK,
    ApiErrorId,
    assert_fte_equals,
    assert_instant_equals,
    assert_money_equals,
    validate_error,
    validate_success,
)
from test_helpers.factories import review_decision_payload
from test_helpers.fixtures import (
    accept_wage_submission,
    add_ucc_data_set,
    add_wage_submission,
    file_report,
    new_scenario,
    read_cost_report,
    run_stepdown,
    setup_resident_with_rotation,
    setup_two_center_report,
    submit_wage_submission,
    void_rotation,
)

MINIMAL_SURVEY_INPUTS = {
    "total_salaries_cents": 5000000000,
    "total_paid_hours": 2000000.00,
}


def _two_center_report_ready_to_file(api):
    """The two-center report with every filing precondition satisfied."""
    scenario = setup_two_center_report(api)
    run_stepdown(api, scenario, "SINGLE_APPORTIONMENT")
    accept_wage_submission(api, scenario)
    add_ucc_data_set(api, scenario)
    return scenario


def test_a_new_wage_index_submission_opens_in_draft(api):
    """Creation alone leaves the survey at DRAFT with no revisions, no staffed
    categories and no occupational-mix-adjusted wage.

    PRD 3.5: "A new submission begins at `status` `DRAFT` with `revision_number` at 0 and `review_note` at null."

    PRD 3.5: "When `occ_mix_category_count` is fewer than 3, `occ_mix_adjusted_ahw_cents` is null and no weighting is attempted."

    Design: Corner/state_machines/wage_index_submission_starts_in_draft
    """
    scenario = new_scenario(api)

    submission = validate_success(
        api.create_wage_index_submission(
            scenario["report_id"], dict(MINIMAL_SURVEY_INPUTS), scenario["analyst"]
        ),
        201,
    )

    assert submission["status"] == "DRAFT"
    assert submission["revision_number"] == 0
    assert submission["review_note"] is None
    assert submission["occ_mix_category_count"] == 0
    assert submission["reported_hours_total"] == 0
    assert submission["occ_mix_adjusted_ahw_cents"] is None

    report = read_cost_report(api, scenario)
    assert report["wage_data_status"] == "NOT_STARTED"


def test_filing_a_draft_report_stamps_the_clock_and_recomputes_the_fte_block(api):
    """The report advances to FILED at the logical clock instant, keeps
    amendment_count at 0, and its GME block recomputes to zero with no rotations.

    PRD 3.1: "The first successful filing stamps `filed_at` from the logical clock; every successful filing after the first increments `amendment_count` by one."

    PRD 3.8: "Reaching `FINAL_SETTLED` by either path stamps the report's `allowable_cost_per_discharge_cents` as `total_allowable_cost_cents` divided by `medicare_discharges`, rounded half up to a whole cent, taking the value 0 when `medicare_discharges` is 0; before final settlement that field reads 0."

    Design: Corner/state_machines/file_a_draft_report_moves_it_to_filed_and_stamps_filed_at
    """
    scenario = _two_center_report_ready_to_file(api)

    report = file_report(api, scenario)

    assert report["status"] == "FILED"
    assert_instant_equals(report["filed_at"], DEFAULT_CLOCK, "filed_at")
    assert report["amendment_count"] == 0
    assert report["wage_data_status"] == "VERIFIED"
    assert report["allocation_status"] == "CURRENT"
    assert_fte_equals(
        report["unweighted_fte_days_total"], 0.0000, "unweighted_fte_days_total"
    )
    assert report["unweighted_fte_total"] == 0.00
    assert report["capped_unweighted_fte"] == 0.00
    assert report["weighted_fte_total"] == 0.00
    assert report["rolling_average_fte"] == 0.00
    assert_money_equals(
        report["allowable_cost_per_discharge_cents"],
        0,
        "allowable_cost_per_discharge_cents",
    )


def test_filing_a_report_that_is_already_filed_is_refused(api):
    """FILED offers no second filing, so the repeat attempt is a state refusal and
    neither filed_at nor amendment_count moves.

    PRD 3.1: "Attempting to file from any status other than `DRAFT` or `REOPENED` is an `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/filing_an_already_filed_report_is_rejected
    """
    scenario = _two_center_report_ready_to_file(api)
    file_report(api, scenario)

    response = api.file_cost_report(scenario["report_id"], scenario["manager"])

    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    report = read_cost_report(api, scenario)
    assert report["status"] == "FILED"
    assert report["amendment_count"] == 0
    assert_instant_equals(report["filed_at"], DEFAULT_CLOCK, "filed_at")


def test_a_review_decision_before_the_review_opens_is_refused(api):
    """From SUBMITTED the only move is to start the review, so an accept decision
    is refused and the wage axis stays at COLLECTED.

    PRD 3.5: "Any of these three attempted from a status other than `UNDER_REVIEW` is an `ERR_INVALID_STATE_TRANSITION`."

    PRD 3.5: "Both paths require that `reported_hours_total` not exceed `total_paid_hours`, recompute the average hourly wage figures, set the report's `wage_data_status` to `COLLECTED`, and increment the report's `version`."

    Design: Corner/state_machines/review_decision_before_start_review_is_rejected
    """
    scenario = new_scenario(api)
    add_wage_submission(api, scenario)
    submit_wage_submission(api, scenario)

    response = api.record_wage_index_review_decision(
        scenario["submission_id"],
        review_decision_payload(decision="ACCEPT", review_note="Looks fine"),
        scenario["auditor"],
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    submission = validate_success(
        api.get_wage_index_submission(scenario["submission_id"], scenario["analyst"])
    )
    assert submission["status"] == "SUBMITTED"
    assert submission["review_note"] is None

    report = read_cost_report(api, scenario)
    assert report["wage_data_status"] == "COLLECTED"


def test_voiding_an_already_void_rotation_is_refused(api):
    """VOID is terminal, so the second void is refused and the FTE days are not
    decremented a second time.

    PRD 3.6: "Voiding an assignment that is already `VOID` is an `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/void_an_already_void_rotation_assignment_is_rejected
    """
    scenario = setup_resident_with_rotation(api)
    rotation_id = scenario["base_rotation_id"]
    void_rotation(api, scenario, rotation_id)

    response = api.void_rotation_assignment(rotation_id, scenario["analyst"])

    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    rotation = validate_success(
        api.get_rotation_assignment(rotation_id, scenario["analyst"])
    )
    assert rotation["status"] == "VOID"
    assert_fte_equals(rotation["fte_days"], 0.0000, "fte_days")
    assert rotation["overlap_days"] == 184

    resident = validate_success(
        api.get_resident(scenario["resident_id"], scenario["analyst"])
    )
    assert_fte_equals(resident["assigned_fte_days"], 0.0000, "assigned_fte_days")

    report = read_cost_report(api, scenario)
    assert_fte_equals(
        report["unweighted_fte_days_total"], 0.0000, "unweighted_fte_days_total"
    )


def test_survey_hours_above_the_revised_paid_hours_block_the_submission(api):
    """Correcting total paid hours down to 1800000.00 is permitted and recomputes
    both wage variants, but it then blocks the attestation at 1900000.00 survey
    hours.

    PRD 3.5: "This correction path exists because the hours-verification boundary — reported occupational mix hours exactly equal to total paid hours — is only reachable by editing the totals after the survey responses already exist. Each correction recomputes both average-hourly-wage variants."

    PRD 3.5: "The submission's `reported_hours_total` is the sum of `reported_hours` across its responses, and it may never exceed `total_paid_hours`; **equality is permitted**. This check guards three separate operations — recording a survey response, submitting the wage data, and recording the contractor's accept decision — and in all three the rejection is `ERR_OCC_MIX_HOURS_EXCEED_TOTAL`."

    Design: Corner/state_machines/occ_mix_reported_hours_above_total_paid_hours_blocks_submit
    """
    scenario = new_scenario(api)
    submission = validate_success(
        api.create_wage_index_submission(
            scenario["report_id"], dict(MINIMAL_SURVEY_INPUTS), scenario["analyst"]
        ),
        201,
    )
    for row in CANONICAL_OCC_MIX:
        validate_success(
            api.create_occ_mix_response(
                submission["id"], dict(row), scenario["analyst"]
            ),
            201,
        )

    corrected = validate_success(
        api.update_wage_index_submission(
            submission["id"],
            {"total_paid_hours": 1800000.00},
            scenario["analyst"],
        )
    )
    assert corrected["total_paid_hours"] == 1800000.00
    assert corrected["reported_hours_total"] == 1900000.00
    assert corrected["occ_mix_category_count"] == 3
    assert_money_equals(corrected["unadjusted_ahw_cents"], 2778, "unadjusted_ahw_cents")
    assert_money_equals(
        corrected["occ_mix_adjusted_ahw_cents"], 2860, "occ_mix_adjusted_ahw_cents"
    )
    assert_money_equals(corrected["effective_ahw_cents"], 2860, "effective_ahw_cents")

    response = api.submit_wage_index_submission(submission["id"], scenario["manager"])

    validate_error(response, ApiErrorId.ERR_OCC_MIX_HOURS_EXCEED_TOTAL.value, 422)

    reread = validate_success(
        api.get_wage_index_submission(submission["id"], scenario["analyst"])
    )
    assert reread["status"] == "DRAFT"
    assert reread["revision_number"] == 0

    report = read_cost_report(api, scenario)
    assert report["wage_data_status"] == "NOT_STARTED"
