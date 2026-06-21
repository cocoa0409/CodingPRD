"""CIRR placement outcomes, eligibility boundary, and the GRADUATES_ONLY vs
ALL_ENROLLED placement-rate divergence.

Translates difficulty `boundary_precision_check` (CIRR window) and
`dual_variant_calc` (CIRR half), plus corner `calculations` and `validations`
instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_placement_outcome_payload,
    create_cirr_report_payload,
    assert_placement_outcome,
    setup_graduated_upfront,
    setup_active_enrollment,
    setup_cirr_cohort,
)

COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_cirr_window_at_180_days_is_eligible():
    """PRD §3.12: "it was placed within the reporting window, meaning `placement_days` is present and is 180 or fewer."

    Design: Difficulty/boundary_precision_check/cirr_window_at_180_days_is_eligible
    """
    cohort, applicant, enrollment = setup_graduated_upfront(email="win180@example.com")
    resp = api_client.create_placement_outcome(
        create_placement_outcome_payload(
            enrollment["id"], "EMPLOYED_IN_FIELD", "2026-08-01T00:00:00Z",
            annual_salary_cents=9_000_000, placement_days=180,
        ),
        COMPLIANCE,
    )
    data = validate_success(resp, 201)
    assert data["cirr_eligible"] is True, "placement_days==180 is within the window (<=)"
    assert_placement_outcome(data)


def test_cirr_self_employed_at_180_days_is_eligible():
    """PRD §3.12: "An outcome counts toward CIRR when two conditions both hold: its category is a countable placement — one of `EMPLOYED_IN_FIELD`, `EMPLOYED_OUT_OF_FIELD`, or `SELF_EMPLOYED` — and it was placed within the reporting window, meaning `placement_days` is present and is 180 or fewer."

    Design: Difficulty/boundary_precision_check/cirr_window_at_180_days_is_eligible
    """
    # SELF_EMPLOYED needs no salary; placement_days exactly 180 -> eligible.
    cohort, applicant, enrollment = setup_graduated_upfront(email="self180@example.com")
    resp = api_client.create_placement_outcome(
        create_placement_outcome_payload(
            enrollment["id"], "SELF_EMPLOYED", "2026-08-01T00:00:00Z", placement_days=180,
        ),
        COMPLIANCE,
    )
    data = validate_success(resp, 201)
    assert data["cirr_eligible"] is True, "placement_days==180 is within the window (<=)"


def test_cirr_window_beyond_180_not_eligible():
    """PRD §3.12: "An outcome that is not a countable category, or whose `placement_days` is absent or exceeds 180, is not eligible."

    Design: Corner/calculations/cirr_window_beyond_180_not_eligible
    """
    cohort, applicant, enrollment = setup_graduated_upfront(email="win181@example.com")
    resp = api_client.create_placement_outcome(
        create_placement_outcome_payload(
            enrollment["id"], "EMPLOYED_IN_FIELD", "2026-12-01T00:00:00Z",
            annual_salary_cents=9_000_000, placement_days=181,
        ),
        COMPLIANCE,
    )
    data = validate_success(resp, 201)
    assert data["cirr_eligible"] is False, "placement_days 181 is outside the 180-day window"


def test_cirr_eligibility_out_of_program_not_countable():
    """PRD §3.12: "An outcome counts toward CIRR when two conditions both hold: its category is a countable placement — one of `EMPLOYED_IN_FIELD`, `EMPLOYED_OUT_OF_FIELD`, or `SELF_EMPLOYED` — and it was placed within the reporting window, meaning `placement_days` is present and is 180 or fewer."

    Design: Corner/calculations/cirr_eligibility_out_of_program_not_countable
    """
    cohort, applicant, enrollment = setup_graduated_upfront(email="seeking@example.com")
    resp = api_client.create_placement_outcome(
        create_placement_outcome_payload(
            enrollment["id"], "STILL_SEEKING", "2026-08-01T00:00:00Z", placement_days=30,
        ),
        COMPLIANCE,
    )
    data = validate_success(resp, 201)
    assert data["cirr_eligible"] is False, "STILL_SEEKING is not a countable category"


def test_placement_outcome_employed_missing_salary_returns_salary_required():
    """PRD §3.12: "When the category is `EMPLOYED_IN_FIELD` or `EMPLOYED_OUT_OF_FIELD`, the `annual_salary_cents` is required, and an employed outcome missing it is rejected with `ERR_SALARY_REQUIRED`."

    Design: Corner/validations/placement_outcome_employed_missing_salary_returns_salary_required
    """
    cohort, applicant, enrollment = setup_graduated_upfront(email="nosal@example.com")
    resp = api_client.create_placement_outcome(
        create_placement_outcome_payload(
            enrollment["id"], "EMPLOYED_IN_FIELD", "2026-06-01T00:00:00Z", placement_days=30,
        ),
        COMPLIANCE,
    )
    validate_error(resp, ApiErrorId.ERR_SALARY_REQUIRED.value)


def test_placement_outcome_non_graduate_returns_not_graduate():
    """PRD §3.12: "An outcome may only be reported for a `GRADUATED` enrollment; reporting one for a non-graduate is rejected with `ERR_OUTCOME_NOT_GRADUATE`."

    Design: Corner/validations/placement_outcome_non_graduate_returns_not_graduate
    """
    # An ACTIVE (non-graduated) enrollment.
    cohort, applicant, enrollment = setup_active_enrollment("UPFRONT", email="active-no-grad@example.com")
    resp = api_client.create_placement_outcome(
        create_placement_outcome_payload(
            enrollment["id"], "SELF_EMPLOYED", "2026-06-01T00:00:00Z", placement_days=30,
        ),
        COMPLIANCE,
    )
    validate_error(resp, ApiErrorId.ERR_OUTCOME_NOT_GRADUATE.value)


def test_cirr_rate_graduates_only_vs_all_enrolled_diverge():
    """PRD §3.12: "The `placement_rate` is `placed_count` divided by a denominator chosen by `denominator_basis` — `graduates_count` under `GRADUATES_ONLY`, or `enrolled_count` under `ALL_ENROLLED` — rounded to four decimal places using round-half-up; when the chosen denominator is zero the rate is defined as zero."
    PRD §3.12: "`graduates_count` is the number of enrollments whose `status` is `GRADUATED`; `enrolled_count` is the number of enrollments whose `status` is `ACTIVE`, `GRADUATED`, `DISMISSED`, or `WITHDRAWN`; and `placed_count` is the number of placement outcomes that are `cirr_eligible` for graduates in this cohort."

    Design: Difficulty/dual_variant_calc/cirr_rate_graduates_only_vs_all_enrolled_diverge
    """
    cohort = setup_cirr_cohort()  # 4 graduates, 6 enrolled-basis, 3 eligible placements.
    coh_id = cohort["id"]
    rep_g = validate_success(
        api_client.create_cirr_report(create_cirr_report_payload(coh_id, "GRADUATES_ONLY"), COMPLIANCE), 201
    )
    assert rep_g["placed_count"] == 3
    assert rep_g["graduates_count"] == 4
    assert rep_g["placement_rate"] == 0.75

    rep_a = validate_success(
        api_client.create_cirr_report(create_cirr_report_payload(coh_id, "ALL_ENROLLED"), COMPLIANCE), 201
    )
    assert rep_a["enrolled_count"] == 6
    assert rep_a["placement_rate"] == 0.5


def test_cirr_same_placed_count_lower_rate_under_all_enrolled():
    """PRD §3.12: "Because the same `placed_count` is divided by a larger denominator under `ALL_ENROLLED`, that basis yields a lower rate for identical placements."

    Design: Difficulty/dual_variant_calc/cirr_rate_graduates_only_vs_all_enrolled_diverge
    """
    cohort = setup_cirr_cohort()
    coh_id = cohort["id"]
    rep_g = validate_success(
        api_client.create_cirr_report(create_cirr_report_payload(coh_id, "GRADUATES_ONLY"), COMPLIANCE), 201
    )
    rep_a = validate_success(
        api_client.create_cirr_report(create_cirr_report_payload(coh_id, "ALL_ENROLLED"), COMPLIANCE), 201
    )
    assert rep_g["placed_count"] == rep_a["placed_count"] == 3
    assert rep_a["placement_rate"] < rep_g["placement_rate"]
