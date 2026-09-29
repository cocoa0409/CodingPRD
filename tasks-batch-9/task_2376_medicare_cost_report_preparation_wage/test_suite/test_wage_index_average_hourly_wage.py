"""The two average-hourly-wage variants and the cyclic desk review that leaves
them alone."""

from test_helpers import (
    assert_money_equals,
    assert_wage_index_submission,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import occ_mix_response_payload
from test_helpers.fixtures import (
    add_wage_submission,
    new_scenario,
    read_cost_report,
    record_wage_review_decision,
    start_wage_review,
    submit_wage_submission,
)

FIVE_CATEGORY_SURVEY = [
    occ_mix_response_payload("RN", 1200000.00, 4200000000),
    occ_mix_response_payload("LPN", 200000.00, 400000000),
    occ_mix_response_payload("NURSE_AIDE", 500000.00, 750000000),
    occ_mix_response_payload("MEDICAL_ASSISTANT", 0.00, 0),
    occ_mix_response_payload("NURSE_PRACTITIONER", 100000.00, 650000000),
]


def _submission_with_five_category_survey(api):
    scenario = new_scenario(api)
    add_wage_submission(api, scenario, occ_mix=FIVE_CATEGORY_SURVEY)
    return scenario


def test_pooled_hourly_wage_caps_wage_related_costs_at_a_quarter_of_salaries(api):
    """The unadjusted variant pools every hour into one ratio and reads 3128
    cents once wage-related costs are floored to 1250000000.

    PRD 3.5: "First, `allowed_wage_related_costs_cents` is the lesser of `wage_related_costs_cents` and one quarter of `total_salaries_cents` rounded down to a whole cent — the wage-related cost cap is 25 percent of total salaries, and it floors rather than rounds."

    Design: Difficulty/dual_variant_calc/wage_index_unadjusted_vs_occ_mix_adjusted_hourly_wage
    """
    scenario = _submission_with_five_category_survey(api)

    submission = validate_success(
        api.submit_wage_index_submission(scenario["submission_id"], scenario["manager"])
    )

    assert_wage_index_submission(submission)
    assert_money_equals(
        submission["allowed_wage_related_costs_cents"],
        1250000000,
        "allowed_wage_related_costs_cents",
    )
    assert_money_equals(submission["unadjusted_ahw_cents"], 3128, "unadjusted_ahw_cents")
    assert submission["reported_hours_total"] == 2000000.00
    assert submission["status"] == "SUBMITTED"
    assert read_cost_report(api, scenario)["wage_data_status"] == "COLLECTED"


def test_occupational_mix_weighting_diverges_from_the_pooled_wage(api):
    """Reweighting the same data by renormalized national targets yields 3240
    cents, and the unstaffed category contributes nothing.

    PRD 3.5: "Because per-category wages are weighted rather than pooled, identical submission data yields a different cents-per-hour result under this variant than under the unadjusted one."

    Design: Difficulty/dual_variant_calc/wage_index_unadjusted_vs_occ_mix_adjusted_hourly_wage
    """
    scenario = _submission_with_five_category_survey(api)

    submission = validate_success(
        api.submit_wage_index_submission(scenario["submission_id"], scenario["manager"])
    )

    assert submission["occ_mix_category_count"] == 4
    assert_money_equals(
        submission["occ_mix_adjusted_ahw_cents"], 3240, "occ_mix_adjusted_ahw_cents"
    )
    assert_money_equals(submission["effective_ahw_cents"], 3240, "effective_ahw_cents")
    assert (
        submission["occ_mix_adjusted_ahw_cents"] != submission["unadjusted_ahw_cents"]
    )

    responses, _meta = validate_paginated(
        api.list_occ_mix_responses(scenario["submission_id"], scenario["analyst"])
    )
    by_category = {row["category"]: row for row in responses}
    assert_money_equals(by_category["RN"]["category_ahw_cents"], 3500, "RN AHW")
    assert_money_equals(by_category["LPN"]["category_ahw_cents"], 2000, "LPN AHW")
    assert_money_equals(
        by_category["NURSE_AIDE"]["category_ahw_cents"], 1500, "NURSE_AIDE AHW"
    )
    assert_money_equals(
        by_category["NURSE_PRACTITIONER"]["category_ahw_cents"],
        6500,
        "NURSE_PRACTITIONER AHW",
    )
    assert by_category["MEDICAL_ASSISTANT"]["category_ahw_cents"] is None


def test_accepted_submission_reopens_into_a_second_review(api):
    """Acceptance is not terminal: a re-opened desk review walks the submission
    back out to CHANGE_REQUESTED and around to ACCEPTED again.

    PRD 3.5: "The full cycle a contested submission travels is therefore from `ACCEPTED` into a re-opened `UNDER_REVIEW`, out to `CHANGE_REQUESTED`, back to `SUBMITTED`, into `UNDER_REVIEW` a second time, and finally to `ACCEPTED` again."

    Design: Difficulty/non_linear_state_machine/wage_index_submission_reenters_review_after_acceptance
    """
    scenario = _submission_with_five_category_survey(api)
    submit_wage_submission(api, scenario)
    start_wage_review(api, scenario)
    accepted = record_wage_review_decision(api, scenario, "ACCEPT", "First acceptance")
    assert accepted["status"] == "ACCEPTED"
    assert accepted["revision_number"] == 0

    reopened = start_wage_review(api, scenario)
    assert reopened["status"] == "UNDER_REVIEW"

    changed = record_wage_review_decision(
        api, scenario, "REQUEST_CHANGE", "Occupational mix hours require re-certification"
    )
    assert changed["status"] == "CHANGE_REQUESTED"

    resubmitted = submit_wage_submission(api, scenario)
    assert resubmitted["status"] == "SUBMITTED"

    start_wage_review(api, scenario)
    final = record_wage_review_decision(
        api, scenario, "ACCEPT", "Second acceptance after revision"
    )
    assert final["status"] == "ACCEPTED"
    assert final["review_note"] == "Second acceptance after revision"

    report = read_cost_report(api, scenario)
    assert report["wage_data_status"] == "VERIFIED"
    assert report["status"] == "DRAFT"


def test_one_lap_through_change_requested_increments_revision_number_once(api):
    """A single trip out to CHANGE_REQUESTED and back moves revision_number from
    0 to 1 while the wage figures stay put.

    PRD 3.5: "the `CHANGE_REQUESTED` path increments `revision_number` by one, which is why `revision_number` counts submissions after the first rather than submissions in total."

    Design: Difficulty/non_linear_state_machine/wage_index_submission_reenters_review_after_acceptance
    """
    scenario = _submission_with_five_category_survey(api)
    submit_wage_submission(api, scenario)
    start_wage_review(api, scenario)
    record_wage_review_decision(api, scenario, "ACCEPT", "First acceptance")

    start_wage_review(api, scenario)
    changed = record_wage_review_decision(
        api, scenario, "REQUEST_CHANGE", "Occupational mix hours require re-certification"
    )
    assert changed["revision_number"] == 0

    resubmitted = submit_wage_submission(api, scenario)
    assert resubmitted["revision_number"] == 1

    start_wage_review(api, scenario)
    final = record_wage_review_decision(
        api, scenario, "ACCEPT", "Second acceptance after revision"
    )
    assert final["revision_number"] == 1
    assert_money_equals(final["unadjusted_ahw_cents"], 3128, "unadjusted_ahw_cents")
    assert_money_equals(
        final["occ_mix_adjusted_ahw_cents"], 3240, "occ_mix_adjusted_ahw_cents"
    )
