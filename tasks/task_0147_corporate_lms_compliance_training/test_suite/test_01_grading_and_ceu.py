"""Dual-variant calculations: final grade (Enrollment) and CEU accrual (Certificate),
plus the passing-score boundary. Queue A (difficulty) + the CEU/grade variant
counterparts from queue B (corner).
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    make_learner_headers,
    TEST_USERS,
    set_clock,
    setup_started_enrollment,
    complete_enrollment,
    submit_attempt,
    get_enrollment,
    get_certificate_for_enrollment,
    quiz_attempt_payload,
)

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# Difficulty/dual_variant_calc/final_grade_highest_vs_latest_on_enrollment
# ===========================================================================
def test_latest_attempt_policy_records_last_score_as_final_grade(api):
    """PRD §3.5: "under LATEST_ATTEMPT it is the score of the attempt with the
    greatest created_at, breaking ties by the greatest attempt_number. The two
    policies diverge whenever the last attempt is not the best."

    Design: Difficulty/dual_variant_calc/final_grade_highest_vs_latest_on_enrollment
    """
    emp, course, started = setup_started_enrollment(
        course_overrides={"passing_score": 70, "max_attempts": 3,
                          "grading_policy": "LATEST_ATTEMPT"},
    )
    learner = make_learner_headers(emp["id"])
    # attempt 1: 65 (fail), re-read version, attempt 2: 68 (fail), attempt 3: 50 (fail, exhausts)
    submit_attempt(started["id"], emp["id"], 65, started["version"])
    v2 = get_enrollment(started["id"], learner)["version"]
    submit_attempt(started["id"], emp["id"], 68, v2)
    v3 = get_enrollment(started["id"], learner)["version"]
    submit_attempt(started["id"], emp["id"], 50, v3)

    enr = get_enrollment(started["id"], learner)
    assert enr["status"] == "FAILED", f"expected FAILED, got {enr['status']}"
    assert enr["final_grade"] == 50, (
        f"LATEST_ATTEMPT final_grade should be the last attempt (50), got {enr['final_grade']}"
    )


def test_latest_attempt_best_score_is_cycle_max_not_final_grade(api):
    """PRD §3.5: "the enrollment's best_score (the highest attempt score in the
    current cycle)".

    Design: Difficulty/dual_variant_calc/final_grade_highest_vs_latest_on_enrollment
    """
    emp, course, started = setup_started_enrollment(
        course_overrides={"passing_score": 70, "max_attempts": 3,
                          "grading_policy": "LATEST_ATTEMPT"},
    )
    learner = make_learner_headers(emp["id"])
    submit_attempt(started["id"], emp["id"], 65, started["version"])
    v2 = get_enrollment(started["id"], learner)["version"]
    submit_attempt(started["id"], emp["id"], 68, v2)
    v3 = get_enrollment(started["id"], learner)["version"]
    submit_attempt(started["id"], emp["id"], 50, v3)

    enr = get_enrollment(started["id"], learner)
    assert enr["best_score"] == 68, (
        f"best_score should be the cycle max (68), got {enr['best_score']}"
    )


# ===========================================================================
# Difficulty/dual_variant_calc/ceu_accrual_standard_vs_score_weighted_on_certificate
# ===========================================================================
def test_score_weighted_ceu_uses_mid_band_multiplier_on_certificate(api):
    """PRD §3.5: "a grade of at least 80 but below 90 takes 0.75 ... the multiplier
    is applied to ceu_credits first and the product is then rounded to two decimal
    places half-up."

    Design: Difficulty/dual_variant_calc/ceu_accrual_standard_vs_score_weighted_on_certificate
    """
    emp, course, started = setup_started_enrollment(
        course_overrides={"content_type": "XAPI", "passing_score": 70,
                          "ceu_credits": 10.00, "ceu_policy": "SCORE_WEIGHTED"},
        enrollment_overrides={"is_required": True},
    )
    submit_attempt(started["id"], emp["id"], 85, started["version"])
    enr = get_enrollment(started["id"])
    cert = get_certificate_for_enrollment(started["id"])
    assert enr["status"] == "COMPLETED"
    assert enr["final_grade"] == 85
    assert cert["ceu_credited"] == pytest.approx(7.50, abs=0.001), (
        f"10.00 * 0.75 = 7.50, got {cert['ceu_credited']}"
    )


def test_score_weighted_ceu_rolls_up_to_employee_total(api):
    """PRD §2.10: "The first, total_ceu_earned, equals the sum of ceu_credited across
    that employee's certificates that are currently ACTIVE."

    Design: Difficulty/dual_variant_calc/ceu_accrual_standard_vs_score_weighted_on_certificate
    """
    emp, course, started = setup_started_enrollment(
        course_overrides={"content_type": "XAPI", "passing_score": 70,
                          "ceu_credits": 10.00, "ceu_policy": "SCORE_WEIGHTED"},
        enrollment_overrides={"is_required": True},
    )
    submit_attempt(started["id"], emp["id"], 85, started["version"])
    holder = get_success_data(api.get_employee(emp["id"], ADMIN))
    assert holder["total_ceu_earned"] == pytest.approx(7.50, abs=0.001), (
        f"total_ceu_earned should equal the single ACTIVE cert's 7.50, got {holder['total_ceu_earned']}"
    )


# ===========================================================================
# Difficulty/boundary_precision_check/passing_score_boundary_ge_on_quiz_attempt
# ===========================================================================
def test_score_equal_to_passing_score_passes_and_completes(api):
    """PRD §3.5: "a computed passed flag that is true exactly when the score is at
    or above the owning course's passing_score."

    Design: Difficulty/boundary_precision_check/passing_score_boundary_ge_on_quiz_attempt
    """
    emp, course, started = setup_started_enrollment(
        course_overrides={"passing_score": 70},
    )
    attempt = submit_attempt(started["id"], emp["id"], 70, started["version"])
    assert attempt["passed"] is True, "score == passing_score must PASS (>= boundary)"
    enr = get_enrollment(started["id"])
    assert enr["status"] == "COMPLETED"


def test_score_equal_to_passing_score_records_that_grade(api):
    """PRD §3.5: "A passing attempt drives the enrollment from IN_PROGRESS to
    COMPLETED ... under HIGHEST_SCORE the final_grade is the maximum score among
    the current cycle's attempts."

    Design: Difficulty/boundary_precision_check/passing_score_boundary_ge_on_quiz_attempt
    """
    emp, course, started = setup_started_enrollment(
        course_overrides={"passing_score": 70},
    )
    submit_attempt(started["id"], emp["id"], 70, started["version"])
    enr = get_enrollment(started["id"])
    assert enr["final_grade"] == 70, f"final_grade should be 70, got {enr['final_grade']}"


# ===========================================================================
# Corner/calculations/ceu_standard_full_credit_on_pass
# ===========================================================================
def test_standard_ceu_credits_full_amount_regardless_of_score(api):
    """PRD §3.5: "Under STANDARD, the full ceu_credits is awarded, rounded to two
    decimal places half-up."

    Design: Corner/calculations/ceu_standard_full_credit_on_pass
    """
    emp, course, enr, cert = complete_enrollment(
        pass_score=72,
        course_overrides={"passing_score": 70, "ceu_credits": 5.00, "ceu_policy": "STANDARD"},
        enrollment_overrides={"is_required": True},
    )
    assert cert["ceu_credited"] == pytest.approx(5.00, abs=0.001), (
        f"STANDARD credits full 5.00 regardless of score, got {cert['ceu_credited']}"
    )
    holder = get_success_data(api.get_employee(emp["id"], ADMIN))
    assert holder["total_ceu_earned"] == pytest.approx(5.00, abs=0.001)


# ===========================================================================
# Corner/calculations/final_grade_highest_score_variant_correct
# ===========================================================================
def test_highest_score_policy_records_max_score_as_final_grade(api):
    """PRD §3.5: "under HIGHEST_SCORE the final_grade is the maximum score among the
    current cycle's attempts."

    Design: Corner/calculations/final_grade_highest_score_variant_correct
    """
    emp, course, started = setup_started_enrollment(
        course_overrides={"passing_score": 70, "max_attempts": 3,
                          "grading_policy": "HIGHEST_SCORE"},
    )
    learner = make_learner_headers(emp["id"])
    submit_attempt(started["id"], emp["id"], 60, started["version"])  # fail, stays IN_PROGRESS
    v3 = get_enrollment(started["id"], learner)["version"]
    submit_attempt(started["id"], emp["id"], 90, v3)  # pass → COMPLETED

    enr = get_enrollment(started["id"], learner)
    assert enr["status"] == "COMPLETED"
    assert enr["final_grade"] == 90, f"HIGHEST_SCORE final_grade should be 90, got {enr['final_grade']}"
    assert enr["best_score"] == 90
