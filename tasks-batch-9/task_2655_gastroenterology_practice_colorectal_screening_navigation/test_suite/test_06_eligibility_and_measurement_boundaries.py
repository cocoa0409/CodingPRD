"""Inclusive boundaries: the screening age window and a measurement window that ends
exactly at the logical clock."""
from test_helpers import (
    QUALITY_OFFICER,
    REFERRAL_COORDINATOR,
    api_client,
    create_screening_episode_payload,
    move_clock,
    open_quality_period,
    read_quality_period,
    register_endoscopist,
    register_patient,
    register_plan,
    validate_error,
    validate_success,
)


def _four_patients_around_the_age_window():
    """Register patients whose whole-year age at a 2026-09-01 index date is exactly 45,
    exactly 44, exactly 75 and exactly 76, and open an average-risk episode for each."""
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    births = {
        "45": ("MRN-45", "1981-09-01"),
        "44": ("MRN-44", "1981-09-02"),
        "75": ("MRN-75", "1951-09-01"),
        "76": ("MRN-76", "1950-09-01"),
    }
    episodes = {}
    for key, (mrn, birth_date) in births.items():
        patient = register_patient(plan["id"], mrn=mrn, birth_date=birth_date)
        response = api_client.create_screening_episode(
            create_screening_episode_payload(patient["id"], "SCREENING_AVERAGE_RISK"),
            REFERRAL_COORDINATOR,
        )
        episodes[key] = validate_success(response, 201)
    return episodes


def test_exactly_forty_five_and_exactly_seventy_five_clear_the_screening_age_window():
    """Otherwise, for `SCREENING_AVERAGE_RISK`, the status is `INELIGIBLE_AGE` when age is
    below 45 or above 75, and `ELIGIBLE` otherwise; both endpoints are inclusive, so
    exactly 45 and exactly 75 are eligible.

    The episode's `index_date` is the calendar date of the logical clock at creation, in
    `YYYY-MM-DD` form, and it anchors both the age calculation and the due date.

    Design: Difficulty/boundary_precision_check/age_exactly_forty_five_is_eligible_and_forty_four_is_not
    """
    episodes = _four_patients_around_the_age_window()

    assert episodes["45"]["index_date"] == "2026-09-01"
    assert episodes["45"]["eligibility_status"] == "ELIGIBLE"
    assert episodes["75"]["eligibility_status"] == "ELIGIBLE"


def test_one_day_short_of_forty_five_and_one_year_past_seventy_five_are_ineligible_age():
    """The evaluation first computes whole-year age at `index_date`: take the index year
    minus the birth year, then subtract one more year if the index month and day, compared
    as a pair, fall before the birth month and day.

    Design: Difficulty/boundary_precision_check/age_exactly_forty_five_is_eligible_and_forty_four_is_not
    """
    episodes = _four_patients_around_the_age_window()

    assert episodes["44"]["eligibility_status"] == "INELIGIBLE_AGE"
    assert episodes["76"]["eligibility_status"] == "INELIGIBLE_AGE"


def test_an_ineligible_episode_is_still_created_and_still_carries_a_due_date():
    """Creation succeeds regardless of the outcome; ineligibility only bites later, when
    someone tries to book a room.

    A `DIAGNOSTIC_FOLLOWUP` episode is due in 90 days; every other indication is due in
    180 days.

    Design: Difficulty/boundary_precision_check/age_exactly_forty_five_is_eligible_and_forty_four_is_not
    """
    episodes = _four_patients_around_the_age_window()

    assert episodes["44"]["due_date"] == "2027-02-28"
    assert episodes["76"]["due_date"] == "2027-02-28"
    assert episodes["45"]["due_date"] == "2027-02-28"
    assert episodes["75"]["due_date"] == "2027-02-28"


def _empty_september_measurement_window():
    """A September measurement window for an endoscopist who performed nothing."""
    move_clock("2026-09-01T00:00:00Z")
    endoscopist = register_endoscopist(adr_benchmark_pct=0.25)
    period = open_quality_period(endoscopist["id"], "2026-09-01", "2026-09-30",
                               attribution_basis="PROCEDURE_DATE")
    return {"period_id": period["id"], "opened": period}


def test_a_window_cannot_be_locked_on_the_day_before_it_ends():
    """It is refused with `ERR_QUALITY_PERIOD_NOT_ENDED` (HTTP 422) unless the calendar date
    of the logical clock is on or after the window's `period_end_date` — a window cannot
    be measured before it has finished.

    A new window begins in `status` `OPEN` with `screening_colonoscopy_count` and
    `adenoma_positive_count` at 0, `remediation_required` false, and `adr_pct`,
    `benchmark_pct`, `benchmark_result`, `remediation_plan`, and `attesting_user_id` all
    empty.

    Design: Difficulty/boundary_precision_check/zero_denominator_quality_period_locks_with_null_adr
    """
    scenario = _empty_september_measurement_window()
    assert scenario["opened"]["status"] == "OPEN"
    assert scenario["opened"]["screening_colonoscopy_count"] == 0
    assert scenario["opened"]["adr_pct"] is None

    move_clock("2026-09-29T23:59:59Z")
    response = api_client.lock_quality_period(scenario["period_id"], QUALITY_OFFICER)
    validate_error(response, "ERR_QUALITY_PERIOD_NOT_ENDED")

    assert read_quality_period(scenario["period_id"])["status"] == "OPEN"


def test_a_zero_denominator_window_locks_with_a_null_rate_and_insufficient_volume():
    """When the denominator is zero, `adr_pct` is `null` rather than 0.0000; otherwise it is
    the numerator divided by the denominator, rounded half-up to four decimal places.

    `benchmark_result` is then `INSUFFICIENT_VOLUME` when `screening_colonoscopy_count` is
    below the minimum measurable volume of one exam — that is, when it is zero — otherwise
    `MET` when `adr_pct` is at or above `benchmark_pct`, and otherwise `MISSED`.

    `remediation_required` is set true only when `benchmark_result` is `MISSED`, and false
    in both other outcomes.

    Design: Difficulty/boundary_precision_check/zero_denominator_quality_period_locks_with_null_adr
    """
    scenario = _empty_september_measurement_window()
    move_clock("2026-09-30T00:00:00Z")
    response = api_client.lock_quality_period(scenario["period_id"], QUALITY_OFFICER)
    locked = validate_success(response, 200)

    assert locked["status"] == "LOCKED"
    assert locked["screening_colonoscopy_count"] == 0
    assert locked["adenoma_positive_count"] == 0
    assert locked["adr_pct"] is None
    assert locked["benchmark_result"] == "INSUFFICIENT_VOLUME"
    assert locked["remediation_required"] is False
    assert locked["benchmark_pct"] == 0.25
