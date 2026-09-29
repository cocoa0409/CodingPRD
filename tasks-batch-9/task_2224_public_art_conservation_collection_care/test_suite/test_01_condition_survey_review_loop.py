"""The surveyor/conservator negotiation loop and the treatment trigger boundary.

A condition survey shuttles between the surveyor and the chief conservator until
the conservator either finalizes it or exhausts the two permitted revision
rounds.  Finalization then computes the index whose relation to the 55.0
treatment trigger decides whether the work is flagged for treatment.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_condition_assessment
from test_helpers.test_users import (
    SECOND_SURVEYOR_USER_ID,
    SURVEYOR_USER_ID,
    TEST_USERS,
    make_surveyor_headers,
)


def _survey_returned_once(api):
    """A documented survey that has been round the loop once already."""
    register = fixtures.setup_register(api)
    assessment = fixtures.setup_assessment_submitted(
        api, register["artwork"]["id"], assessed_on="2026-07-15"
    )
    assessment = validate_success(
        api.request_assessment_revision(
            assessment["id"],
            {"reviewer_note": "add mount detail photograph"},
            TEST_USERS["chief_conservator_headers"],
        )
    )
    assert assessment["status"] == "REVISION_REQUESTED"
    assert assessment["revision_rounds"] == 1
    return register, assessment


def test_resubmission_restamps_the_most_recent_surveyor(api):
    """PRD §3.2: "Submission moves the survey to `SUBMITTED`, from `DRAFT` on the
    first pass and from `REVISION_REQUESTED` on any later pass, and may carry an
    optional `surveyor_note`."
    PRD §3.2: "Every submission stamps `submitted_by_user_id` with the acting
    `X-User-ID`, restamping it on each round so that the identity recorded is
    always that of the most recent submitter."

    Design: Difficulty/non_linear_state_machine/assessment_revision_loop_reenters_submitted_until_round_cap
    """
    _register, assessment = _survey_returned_once(api)
    assert assessment["submitted_by_user_id"] == SURVEYOR_USER_ID

    resubmitted = validate_success(
        api.submit_condition_assessment(
            assessment["id"],
            {"surveyor_note": "round 2 resubmitted by a different surveyor"},
            make_surveyor_headers(SECOND_SURVEYOR_USER_ID),
        )
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["submitted_by_user_id"] == SECOND_SURVEYOR_USER_ID
    assert resubmitted["revision_rounds"] == 1
    assert_condition_assessment(resubmitted)


def test_survey_re_enters_submitted_after_the_second_revision_round(api):
    """PRD §3.2: "Review belongs to the `ChiefConservator`, who may send a
    `SUBMITTED` survey back with a mandatory `reviewer_note`, moving it
    `SUBMITTED → REVISION_REQUESTED` and increasing `revision_rounds` by one."
    PRD §3.2: "The loop `SUBMITTED → REVISION_REQUESTED → SUBMITTED` is the
    negotiation channel between surveyor and conservator, and it closes when the
    conservator finalizes instead of returning the work."

    Design: Difficulty/non_linear_state_machine/assessment_revision_loop_reenters_submitted_until_round_cap
    """
    _register, assessment = _survey_returned_once(api)
    validate_success(
        api.submit_condition_assessment(
            assessment["id"],
            {"surveyor_note": "round 2"},
            make_surveyor_headers(SECOND_SURVEYOR_USER_ID),
        )
    )
    returned_again = validate_success(
        api.request_assessment_revision(
            assessment["id"],
            {"reviewer_note": "structural subscore still disputed"},
            TEST_USERS["chief_conservator_headers"],
        )
    )
    assert returned_again["status"] == "REVISION_REQUESTED"
    assert returned_again["revision_rounds"] == 2

    third_pass = validate_success(
        api.submit_condition_assessment(
            assessment["id"],
            {"surveyor_note": "round 3"},
            make_surveyor_headers(SURVEYOR_USER_ID),
        )
    )
    assert third_pass["status"] == "SUBMITTED"
    assert third_pass["submitted_by_user_id"] == SURVEYOR_USER_ID
    assert third_pass["revision_rounds"] == 2


def test_third_revision_request_is_refused_at_the_round_ceiling(api):
    """PRD §3.2: "Two rounds are the ceiling: the request is permitted only while
    `revision_rounds` is below 2, so a third attempt to send the same survey back
    is refused with `ERR_REVISION_LIMIT_REACHED`."

    Design: Difficulty/non_linear_state_machine/assessment_revision_loop_reenters_submitted_until_round_cap
    """
    _register, assessment = _survey_returned_once(api)
    validate_success(
        api.submit_condition_assessment(
            assessment["id"], {}, make_surveyor_headers(SECOND_SURVEYOR_USER_ID)
        )
    )
    validate_success(
        api.request_assessment_revision(
            assessment["id"],
            {"reviewer_note": "structural subscore still disputed"},
            TEST_USERS["chief_conservator_headers"],
        )
    )
    validate_success(
        api.submit_condition_assessment(
            assessment["id"], {}, make_surveyor_headers(SURVEYOR_USER_ID)
        )
    )

    refused = api.request_assessment_revision(
        assessment["id"],
        {"reviewer_note": "one more pass"},
        TEST_USERS["chief_conservator_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_REVISION_LIMIT_REACHED.value)

    unchanged = fixtures.read_assessment(api, assessment["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["revision_rounds"] == 2
    assert unchanged["photo_count"] == 3


def _two_interior_bronzes(api):
    """Two identical BRONZE works in an interior atrium, surveyed on the same day."""
    register = fixtures.setup_register(
        api,
        site={
            "site_code": "HALL-1",
            "name": "City Hall Atrium",
            "exposure_class": "INTERIOR",
            "capacity_units": 20,
        },
        artwork={"accession_number": "2024.010", "title": "Atrium Bronze A"},
    )
    work_b = fixtures.create_artwork(
        api,
        register["artist"]["id"],
        register["site"]["id"],
        accession_number="2024.011",
        title="Atrium Bronze B",
        acquisition_document_ref="DEED-2014-011",
    )
    return register, work_b


def test_index_exactly_at_the_treatment_trigger_leaves_the_work_monitored(api):
    """PRD §3.2: "The index sorts the survey into a `recommendation` band: `NONE`
    when the index is 75.0 or above, `ROUTINE` when it is at least 55.0 but below
    75.0, `PRIORITY` when it is at least 30.0 but below 55.0, and `URGENT` when it
    is below 30.0."
    PRD §3.2: "Hop 2: because this survey is now finalized, the work's
    `condition_index` is set to the survey's index, its `treatment_priority_score`
    is recomputed under the single-assessment variant described in §3.9, its
    `priority_basis` is set to `SINGLE_ASSESSMENT`, and its conservation dimension
    moves `MONITORED → TREATMENT_REQUIRED` or `STABILIZED → TREATMENT_REQUIRED`
    when the new index is below 55.0."

    Design: Difficulty/boundary_precision_check/condition_index_exactly_at_treatment_trigger_does_not_flag
    """
    register, _work_b = _two_interior_bronzes(api)
    # BRONZE weights on subscores 2/2/2/2/0 give a weighted defect of 1.80, and an
    # interior site carries no exposure penalty: 100 - 25 x 1.80 - 0.0 = 55.0.
    finalized = fixtures.setup_assessment_finalized(
        api,
        register["artwork"]["id"],
        surface_score=2,
        structural_score=2,
        coating_score=2,
        mount_score=2,
        graffiti_score=0,
    )
    assert finalized["condition_index"] == 55.0
    assert finalized["recommendation"] == "ROUTINE"

    work = fixtures.read_artwork(api, register["artwork"]["id"])
    assert work["condition_index"] == 55.0
    assert work["conservation_status"] == "MONITORED"
    assert work["custody_status"] == "ON_VIEW"


def test_index_one_notch_below_the_trigger_flags_the_work_for_treatment(api):
    """PRD §3.2: "The value 55.0 is the collection's treatment trigger, and it
    recurs throughout this specification."
    PRD §3.2: "Hop 2: because this survey is now finalized, the work's
    `condition_index` is set to the survey's index, its `treatment_priority_score`
    is recomputed under the single-assessment variant described in §3.9, its
    `priority_basis` is set to `SINGLE_ASSESSMENT`, and its conservation dimension
    moves `MONITORED → TREATMENT_REQUIRED` or `STABILIZED → TREATMENT_REQUIRED`
    when the new index is below 55.0."

    Design: Difficulty/boundary_precision_check/condition_index_exactly_at_treatment_trigger_does_not_flag
    """
    _register, work_b = _two_interior_bronzes(api)
    # One point of graffiti raises the weighted defect to 1.90: 100 - 47.5 = 52.5.
    finalized = fixtures.setup_assessment_finalized(
        api,
        work_b["id"],
        surface_score=2,
        structural_score=2,
        coating_score=2,
        mount_score=2,
        graffiti_score=1,
    )
    assert finalized["condition_index"] == 52.5
    assert finalized["recommendation"] == "PRIORITY"

    work = fixtures.read_artwork(api, work_b["id"])
    assert work["condition_index"] == 52.5
    assert work["conservation_status"] == "TREATMENT_REQUIRED"


def test_priority_scores_either_side_of_the_trigger_follow_the_deficit(api):
    """PRD §3.9: "The **deficit** is 100 less the source survey's `condition_index`."
    PRD §3.9: "Under the **single-assessment** variant, which runs as Cascade A hop
    2 when a survey is finalized, the source is that very survey and the deferral
    day count is pinned to zero, so the deferral factor is exactly 1.0 and the
    score is the undeferred product; the work's `priority_basis` is set to
    `SINGLE_ASSESSMENT`."

    Design: Difficulty/boundary_precision_check/condition_index_exactly_at_treatment_trigger_does_not_flag
    """
    register, work_b = _two_interior_bronzes(api)
    fixtures.setup_assessment_finalized(
        api,
        register["artwork"]["id"],
        surface_score=2,
        structural_score=2,
        coating_score=2,
        mount_score=2,
        graffiti_score=0,
    )
    fixtures.setup_assessment_finalized(
        api,
        work_b["id"],
        surface_score=2,
        structural_score=2,
        coating_score=2,
        mount_score=2,
        graffiti_score=1,
    )

    # Deficit 45.0 and 47.5, LANDMARK 1.5, INTERIOR 1.0, deferral pinned at 1.0.
    work_a = fixtures.read_artwork(api, register["artwork"]["id"])
    assert work_a["treatment_priority_score"] == 67.50
    assert work_a["priority_basis"] == "SINGLE_ASSESSMENT"

    flagged = fixtures.read_artwork(api, work_b["id"])
    assert flagged["treatment_priority_score"] == 71.25
    assert flagged["priority_basis"] == "SINGLE_ASSESSMENT"
