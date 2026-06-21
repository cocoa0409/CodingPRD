"""Combinatorial formulas: weighted path progress (pinned rounding order) and the
non-linear, clamped compliance score. Queue A (difficulty) + the path-progress
computed-read corner instance.
"""
import pytest

from test_helpers import (
    get_success_data,
    TEST_USERS,
    set_clock,
    create_employee,
    create_published_course,
    create_enrollment,
    setup_published_path,
    create_path_enrollment,
    complete_child_step,
    get_path_enrollment,
    get_employee_dashboard,
    get_enrollment,
    make_learner_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# Difficulty/combinatorial_formula/path_progress_rounding_order_pinned_sum_then_round
# ===========================================================================
def test_path_progress_two_of_three_equal_steps_rounds_to_66_67(api):
    """PRD §3.7: "The progress percentage is the earned weight divided by the total
    weight, multiplied by 100, and rounded once to two decimal places half-up. The
    rounding order is binding: form the single ratio of earned to total weight, scale
    to a percentage, and round that one result — never round each step's contribution
    and sum the rounded pieces."

    Design: Difficulty/combinatorial_formula/path_progress_rounding_order_pinned_sum_then_round
    """
    set_clock()
    emp = create_employee()
    path, courses = setup_published_path(num_steps=3, enforce_sequence=False,
                                         weights=[1, 1, 1], set_clock_first=False)
    pe = create_path_enrollment(emp["id"], path["id"])
    complete_child_step(pe["id"], courses[0]["id"], emp["id"], pass_score=90)
    complete_child_step(pe["id"], courses[1]["id"], emp["id"], pass_score=90)

    refreshed = get_path_enrollment(pe["id"])
    assert refreshed["progress_pct"] == pytest.approx(66.67, abs=0.001), (
        f"2/3 sum-then-round must be 66.67 (not 66.66), got {refreshed['progress_pct']}"
    )


def test_path_progress_incomplete_path_stays_in_progress(api):
    """PRD §3.7: "until every mandatory step is satisfied it stays IN_PROGRESS."

    Design: Difficulty/combinatorial_formula/path_progress_rounding_order_pinned_sum_then_round
    """
    set_clock()
    emp = create_employee()
    path, courses = setup_published_path(num_steps=3, enforce_sequence=False,
                                         weights=[1, 1, 1], set_clock_first=False)
    pe = create_path_enrollment(emp["id"], path["id"])
    complete_child_step(pe["id"], courses[0]["id"], emp["id"], pass_score=90)
    complete_child_step(pe["id"], courses[1]["id"], emp["id"], pass_score=90)

    refreshed = get_path_enrollment(pe["id"])
    assert refreshed["status"] == "IN_PROGRESS", (
        f"two of three mandatory steps satisfied → still IN_PROGRESS, got {refreshed['status']}"
    )


# ===========================================================================
# Difficulty/combinatorial_formula/compliance_score_nonlinear_three_input_clamp
# ===========================================================================
def _setup_compliance_score_scenario(api):
    """Employee with 2 required enrollments: A completed (cert ACTIVE), B started then
    expired at tier 2 (16 days overdue). Returns (emp, enr_a, enr_b)."""
    set_clock("2026-01-01T00:00:00.000Z")
    emp = create_employee(department="SALES", job_role="IC")
    course_a = create_published_course(passing_score=70)
    course_b = create_published_course(passing_score=70)
    learner = make_learner_headers(emp["id"])

    enr_a = create_enrollment(emp["id"], course_a["id"], is_required=True, due_in_days=24)
    started_a = get_success_data(api.start_enrollment(enr_a["id"], learner))
    get_success_data(
        api.create_quiz_attempt(
            enr_a["id"], {"score": 90, "expected_enrollment_version": started_a["version"]}, learner
        )
    )

    enr_b = create_enrollment(emp["id"], course_b["id"], is_required=True, due_in_days=24)
    get_success_data(api.start_enrollment(enr_b["id"], learner))

    set_clock("2026-02-10T00:00:00.000Z")  # 40 days after due-base; B due 2026-01-25 → 16 days overdue
    get_success_data(api.run_escalations(ADMIN))
    return emp, enr_a, enr_b


def test_compliance_score_overdue_enrollment_reaches_tier_two(api):
    """PRD §3.9: "from 8 through 30 days the tier is 2".

    Design: Difficulty/combinatorial_formula/compliance_score_nonlinear_three_input_clamp
    """
    emp, enr_a, enr_b = _setup_compliance_score_scenario(api)
    b = get_enrollment(enr_b["id"])
    assert b["status"] == "EXPIRED", f"overdue NOT-completed enrollment should be EXPIRED, got {b['status']}"
    assert b["escalation_tier"] == 2, (
        f"16 days overdue lands tier 2, got {b['escalation_tier']}"
    )


# ===========================================================================
# Corner/endpoints/get_path_enrollment_computed_progress_read
# ===========================================================================
def test_fresh_path_enrollment_reads_zero_progress_not_started(api):
    """PRD §3.7: "The path enrollment begins NOT_STARTED with progress_pct 0 ...
    reading one recomputes its progress_pct."

    Design: Corner/endpoints/get_path_enrollment_computed_progress_read
    """
    set_clock()
    emp = create_employee()
    path, courses = setup_published_path(num_steps=1, enforce_sequence=True, set_clock_first=False)
    pe = create_path_enrollment(emp["id"], path["id"])
    refreshed = get_path_enrollment(pe["id"])
    assert refreshed["progress_pct"] == pytest.approx(0, abs=0.001), (
        f"no step complete → progress 0, got {refreshed['progress_pct']}"
    )
    assert refreshed["status"] == "NOT_STARTED"
