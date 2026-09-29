"""Values sitting exactly on a threshold, and empty denominators."""

import pytest

from test_helpers import (
    acquire_exam,
    add_personnel,
    assert_instant_equals,
    assert_personnel_state,
    assert_unit_image_ledger,
    create_draft_survey,
    personnel_payload,
    post_ce_credit,
    post_volume_credit,
    read_exam,
    read_personnel,
    read_unit,
    validate_success,
)


@pytest.fixture
def two_draft_surveys(core):
    """Two draft surveys of different types sharing one window on the same unit."""
    annual = create_draft_survey(
        core,
        survey_type="ANNUAL",
        effective_start="2026-07-01T00:00:00Z",
        effective_end="2027-07-01T00:00:00Z",
    )
    mobile = create_draft_survey(
        core,
        survey_type="MOBILE",
        effective_start="2026-07-01T00:00:00Z",
        effective_end="2027-07-01T00:00:00Z",
    )
    core["annual_id"] = annual["id"]
    core["mobile_id"] = mobile["id"]
    return core


def test_score_of_six_point_zero_and_dose_of_three_pass_on_the_boundary(api, two_draft_surveys):
    """Both comparisons are inclusive, so the boundary belongs to the passing side.

    PRD: "The survey passes when all three of the following hold simultaneously:
    the `phantom_score` is at least 6.0; the `mean_glandular_dose_mgy` is at most
    3.00; and `critical_deficiency_codes` is empty."

    Design: Difficulty/boundary_precision_check/survey_phantom_score_and_dose_pass_exactly_on_their_boundaries
    """
    core = two_draft_surveys
    survey = validate_success(
        api.submit_physicist_survey(
            core["annual_id"],
            {
                "phantom_score": 6.0,
                "mean_glandular_dose_mgy": 3.00,
                "outcome_note": "Score exactly at the minimum, dose exactly at the ceiling",
            },
            core["phys_headers"],
        )
    )
    assert survey["status"] == "PASSED"
    unit = read_unit(core["unit_id"])
    assert_instant_equals(
        unit["last_passed_survey_end"], "2027-07-01T00:00:00Z", "last_passed_survey_end"
    )


def test_score_one_tenth_below_the_floor_fails_without_leaving_service(api, two_draft_surveys):
    """5.9 is not at least 6.0, and a failure with no deficiency codes keeps the unit in service.

    PRD: "Level two, caused by that, moves the unit's `accreditation_status` to
    `PROBATION` — this fires from `ACCREDITED`, from `PROVISIONAL` and from
    `REACCREDITATION_DUE` alike — and, only when the deciding survey's
    `critical_deficiency_codes` is non-empty, additionally moves the unit's
    `operational_state` from `IN_SERVICE` to `OUT_OF_SERVICE`."

    Design: Difficulty/boundary_precision_check/survey_phantom_score_and_dose_pass_exactly_on_their_boundaries
    """
    core = two_draft_surveys
    validate_success(
        api.submit_physicist_survey(
            core["annual_id"],
            {
                "phantom_score": 6.0,
                "mean_glandular_dose_mgy": 3.00,
                "outcome_note": "Score exactly at the minimum, dose exactly at the ceiling",
            },
            core["phys_headers"],
        )
    )
    survey = validate_success(
        api.submit_physicist_survey(
            core["mobile_id"],
            {
                "phantom_score": 5.9,
                "mean_glandular_dose_mgy": 3.00,
                "outcome_note": "Score one tenth below the minimum",
            },
            core["phys_headers"],
        )
    )
    assert survey["status"] == "FAILED_ACTION_REQUIRED"
    assert survey["remediation_attempts"] == 0
    unit = read_unit(core["unit_id"])
    assert unit["survey_compliance"] == "FAILED"
    assert unit["accreditation_status"] == "PROBATION"
    assert unit["operational_state"] == "IN_SERVICE"
    assert_instant_equals(
        unit["last_passed_survey_end"], "2027-07-01T00:00:00Z", "last_passed_survey_end"
    )


@pytest.fixture
def edge_dated_volume_credits(core):
    """Two identical technologists whose volume credits straddle the lookback edge."""
    second = add_personnel(
        core["facility_id"],
        personnel_payload(
            "TECHNOLOGIST",
            full_name="Tara Tech",
            initial_qualification_on="2024-02-15T00:00:00Z",
        ),
    )
    core["tech2_id"] = second["id"]
    for person_id, volume_date in (
        (core["tech_id"], "2024-08-01T00:00:00Z"),
        (second["id"], "2024-07-31T00:00:00Z"),
    ):
        post_ce_credit(
            core,
            person_id,
            15,
            awarded_on="2026-01-01T00:00:00Z",
            source_note="Digital breast tomosynthesis refresher",
        )
        post_volume_credit(
            core,
            person_id,
            200,
            awarded_on=volume_date,
            modality="DBT_3D",
            source_note="Volume credit posted against the lookback edge",
        )
    return core


def test_volume_credit_dated_exactly_on_the_lookback_edge_still_counts(
    api, edge_dated_volume_credits
):
    """A credit awarded exactly 730 days before the clock is inside the closed window.

    PRD: "`volume_credit_24mo` is the sum of `exam_count` across the person's
    `READ_VOLUME` credits whose `awarded_on` falls in the window that begins 730
    days before the clock and ends at the clock, again with both edges included."

    Design: Difficulty/boundary_precision_check/read_volume_credit_on_the_exact_lookback_left_edge_still_counts
    """
    core = edge_dated_volume_credits
    person = validate_success(
        api.run_qualification_review(
            core["tech_id"], core["coord_headers"], {"review_note": "Edge-inclusive volume credit"}
        )
    )
    assert_personnel_state(
        person,
        ce_status="COMPLIANT",
        qualification_status="QUALIFIED",
        ce_hours_36mo=15.00,
        volume_credit_24mo=200,
    )
    assert person["ce_deadline_at"] is None
    assert_instant_equals(
        person["last_qualification_review_at"],
        "2026-08-01T00:00:00Z",
        "last_qualification_review_at",
    )


def test_volume_credit_one_day_before_the_edge_falls_outside_and_forces_grace(
    api, edge_dated_volume_credits
):
    """731 days back is outside the window, so the same 200 exams count as zero.

    PRD: "A shortfall exists when the accumulated hours fall below the role's hour
    requirement, or the accumulated volume falls below the role's volume
    requirement, or both."

    Design: Difficulty/boundary_precision_check/read_volume_credit_on_the_exact_lookback_left_edge_still_counts
    """
    core = edge_dated_volume_credits
    person = validate_success(
        api.run_qualification_review(
            core["tech2_id"], core["coord_headers"], {"review_note": "Volume credit one day stale"}
        )
    )
    assert_personnel_state(
        person,
        ce_status="GRACE",
        qualification_status="QUALIFIED",
        ce_hours_36mo=15.00,
        volume_credit_24mo=0,
    )
    assert_instant_equals(person["ce_deadline_at"], "2026-10-30T00:00:00Z", "ce_deadline_at")
    assert_instant_equals(
        read_personnel(core["tech2_id"])["last_qualification_review_at"],
        "2026-08-01T00:00:00Z",
        "last_qualification_review_at",
    )


def test_an_unimaged_unit_reports_null_repeat_rates_rather_than_zero(api, core):
    """An empty image ledger has no denominator, so both rates read null.

    PRD: "Its image ledger starts empty: `total_images_acquired` and
    `repeat_images_acquired` at 0, both `image_based_repeat_rate_pct` and
    `patient_based_repeat_rate_pct` null, and `repeat_rate_flag` false."

    Design: Difficulty/boundary_precision_check/unit_repeat_rates_are_null_on_an_empty_ledger_and_zero_once_imaged
    """
    unit = read_unit(core["unit_id"])
    assert_unit_image_ledger(
        unit,
        total_images_acquired=0,
        repeat_images_acquired=0,
        image_based_repeat_rate_pct=None,
        patient_based_repeat_rate_pct=None,
    )
    assert unit["repeat_rate_flag"] is False


def test_the_first_imaged_exam_turns_the_null_rates_into_a_real_zero(api, core):
    """A four-image exam with no repeats yields 0.00, which is not the earlier null.

    PRD: "The image-based rate, `image_based_repeat_rate_pct`, is 100 multiplied by
    `repeat_images_acquired`, divided by `total_images_acquired`, rounded half up to
    two decimal places — and it is null when `total_images_acquired` is 0."

    Design: Difficulty/boundary_precision_check/unit_repeat_rates_are_null_on_an_empty_ledger_and_zero_once_imaged
    """
    exam = acquire_exam(
        core,
        patient_ref="PT-9501",
        performed_at="2026-07-20T00:00:00Z",
        original_image_count=4,
    )
    unit = read_unit(core["unit_id"])
    assert_unit_image_ledger(
        unit,
        total_images_acquired=4,
        repeat_images_acquired=0,
        image_based_repeat_rate_pct=0.00,
        patient_based_repeat_rate_pct=0.00,
    )
    assert unit["repeat_rate_flag"] is False
    assert read_exam(exam["id"])["repeat_image_count"] == 0
