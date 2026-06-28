"""Skills-test scheduling, grading, the weighted-score formula, the retake cycle, and
the examiner constraints.

Translates queue A (combinatorial_formula/skills_weighted_score_three_input_threshold_branch,
non_linear_state_machine/skills_test_fail_retake_cycle_supersedes) and queue B
(calculations, validations, errors) instances.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_program, create_truck, create_instructor,
    create_enrollment_in_training, book_and_complete_session,
    setup_enrollment_test_ready, setup_scheduled_skills_test,
    schedule_skills_test, grade_test,
    make_instructor_headers, make_examiner_headers,
)

ADMIN = TEST_USERS["school_admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


# ---- Queue A: combinatorial_formula / skills_weighted_score_three_input_threshold_branch ----

def test_weighted_score_three_input_pass_branch():
    """PRD §3.5: "the system computes the weighted_score as three-tenths of the pre-trip
    score plus three-tenths of the basic-control score plus four-tenths of the road
    score, rounded half-up to two decimal places. The outcome is PASS when the weighted
    score is at least the program's skills_pass_threshold, and FAIL otherwise".

    Design: Difficulty/combinatorial_formula/skills_weighted_score_three_input_threshold_branch
    """
    ctx = setup_scheduled_skills_test(skills_pass_threshold=80)
    test = ctx["test"]
    # 0.30*80 + 0.30*75 + 0.40*84 = 24 + 22.5 + 33.6 = 80.10 -> PASS at threshold 80.
    graded = grade_test(test["id"], ctx["examiner"]["id"], 80, 75, 84)
    assert graded["weighted_score"] == pytest.approx(80.1, abs=0.001)
    assert graded["outcome"] == "PASS"
    assert graded["status"] == "GRADED"


def test_weighted_score_no_single_input_determines_outcome():
    """PRD §3.5: "the system computes the weighted_score as three-tenths of the pre-trip
    score plus three-tenths of the basic-control score plus four-tenths of the road
    score, rounded half-up to two decimal places."

    Design: Difficulty/combinatorial_formula/skills_weighted_score_three_input_threshold_branch
    """
    ctx = setup_scheduled_skills_test(skills_pass_threshold=80)
    # Same inputs as the canonical instance: 80/75/84 -> 80.10 (a value no single input
    # equals), confirming the weighted combination.
    graded = grade_test(ctx["test"]["id"], ctx["examiner"]["id"], 80, 75, 84)
    assert graded["weighted_score"] == pytest.approx(80.1, abs=0.001)


# ---- Queue A: non_linear_state_machine / skills_test_fail_retake_cycle_supersedes ----

def test_failed_test_retake_supersedes_prior_and_keeps_test_ready():
    """PRD §3.5: "After a graded failure, the Registrar schedules a fresh retake whose
    supersedes_test_id is set to the prior graded-fail test, forming the retake loop."
    PRD §3.5: "The outcome is PASS when the weighted score is at least the program's
    skills_pass_threshold, and FAIL otherwise".

    Design: Difficulty/non_linear_state_machine/skills_test_fail_retake_cycle_supersedes
    """
    ctx = setup_scheduled_skills_test(skills_pass_threshold=80)
    test1 = ctx["test"]
    # 70/70/70 -> 70.0 -> FAIL (enrollment stays TEST_READY since no PASS bubble).
    graded1 = grade_test(test1["id"], ctx["examiner"]["id"], 70, 70, 70)
    assert graded1["outcome"] == "FAIL"
    # Schedule a retake superseding the failed test.
    test2 = schedule_skills_test(ctx["enrollment_id"], ctx["examiner"]["id"],
                                supersedes_test_id=test1["id"])
    assert test2["supersedes_test_id"] == test1["id"]
    assert test2["status"] == "SCHEDULED"
    enr = validate_success(api_client.get_enrollment(ctx["enrollment_id"], REGISTRAR))
    assert enr["status"] == "TEST_READY"


def test_failed_test_outcome_is_fail_below_threshold():
    """PRD §3.5: "The outcome is PASS when the weighted score is at least the program's
    skills_pass_threshold, and FAIL otherwise — the comparison is inclusive at the
    threshold".

    Design: Difficulty/non_linear_state_machine/skills_test_fail_retake_cycle_supersedes
    """
    ctx = setup_scheduled_skills_test(skills_pass_threshold=80)
    graded = grade_test(ctx["test"]["id"], ctx["examiner"]["id"], 70, 70, 70)
    assert graded["weighted_score"] == pytest.approx(70.0, abs=0.001)
    assert graded["outcome"] == "FAIL"


# ---- Queue B: calculations / skills_weighted_score_boundary_exactly_threshold_passes ----

def test_weighted_score_exactly_threshold_passes():
    """PRD §3.5: "the comparison is inclusive at the threshold, so a weighted score
    exactly equal to the threshold passes." PRD §3.5: "When the outcome is PASS, the
    enrollment automatically advances from TEST_READY to PASSED".

    Design: Corner/calculations/skills_weighted_score_boundary_exactly_threshold_passes
    """
    ctx = setup_scheduled_skills_test(
        skills_pass_threshold=80, classroom_required_hours=0, range_required_hours=0,
        road_required_hours=1)
    # 80/80/80 -> weighted 80.0 == threshold -> PASS.
    graded = grade_test(ctx["test"]["id"], ctx["examiner"]["id"], 80, 80, 80)
    assert graded["weighted_score"] == pytest.approx(80.0, abs=0.001)
    assert graded["outcome"] == "PASS"
    enr = validate_success(api_client.get_enrollment(ctx["enrollment_id"], REGISTRAR))
    assert enr["status"] == "PASSED"


# ---- Queue B: validations / errors ----

def test_schedule_skills_test_before_test_ready_rejected():
    """PRD §3.5: "A Registrar schedules a SkillsTest against an enrollment, which is
    permitted only when the enrollment is in TEST_READY status — scheduling while the
    enrollment is not TEST_READY is rejected with ERR_ENROLLMENT_NOT_TEST_READY."

    Design: Corner/validations/schedule_skills_test_before_test_ready_rejected
    """
    program = create_program()
    examiner = create_instructor(full_name="Ed", examiner_certified=True)
    eid, _, _ = create_enrollment_in_training(program["id"])  # TRAINING, not TEST_READY
    resp = api_client.create_skills_test(eid, {"examiner_id": examiner["id"]}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_TEST_READY.value)


def test_examiner_conflict_road_instructor_rejected():
    """PRD §3.5: "the named examiner — identified by examiner_id — must not have
    personally instructed any COMPLETED ROAD session of this same enrollment. An examiner
    who logged the student's road hours as the delivering instructor may not then examine
    that student, and a scheduling attempt that violates this is rejected with
    ERR_EXAMINER_CONFLICT."

    Design: Corner/validations/examiner_conflict_road_instructor_rejected
    """
    program = create_program(
        classroom_required_hours=0, range_required_hours=0, road_required_hours=1,
        skills_pass_threshold=80)
    truck = create_truck()
    examiner = create_instructor(full_name="Ed", examiner_certified=True)
    eid, _, _ = create_enrollment_in_training(program["id"])
    # Ed delivers the ROAD session himself as the instructor.
    book_and_complete_session(eid, "ROAD", examiner["id"], "2026-03-12T09:00:00Z", 60,
                             truck_id=truck["id"])
    enr = validate_success(api_client.get_enrollment(eid, REGISTRAR))
    assert enr["status"] == "TEST_READY"
    # Naming Ed as the examiner violates segregation of duties.
    resp = api_client.create_skills_test(eid, {"examiner_id": examiner["id"]}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_EXAMINER_CONFLICT.value)


def test_examiner_not_certified_rejected():
    """PRD §3.5: "the examiner must be qualified: the instructor referenced by
    examiner_id must have examiner_certified set true and must be certified for the
    program's cdl_class; otherwise the schedule is rejected with
    ERR_EXAMINER_NOT_CERTIFIED."

    Design: Corner/validations/examiner_not_certified_rejected
    """
    program = create_program(
        classroom_required_hours=0, range_required_hours=0, road_required_hours=1,
        skills_pass_threshold=80)
    truck = create_truck()
    instructor = create_instructor(full_name="Ivy")
    non_certified = create_instructor(full_name="Bob", examiner_certified=False)
    eid, _, _ = create_enrollment_in_training(program["id"])
    book_and_complete_session(eid, "ROAD", instructor["id"], "2026-03-12T09:00:00Z", 60,
                             truck_id=truck["id"])
    enr = validate_success(api_client.get_enrollment(eid, REGISTRAR))
    assert enr["status"] == "TEST_READY"
    # Bob is not examiner_certified and never instructed E.
    resp = api_client.create_skills_test(eid, {"examiner_id": non_certified["id"]}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_EXAMINER_NOT_CERTIFIED.value)


def test_grade_score_out_of_range_rejected():
    """PRD §2.8: "a component score outside the inclusive 0 to 100 range yields
    ERR_INVALID_REQUEST." PRD §3.5: "each on the inclusive 0 to 100 scale."

    Design: Corner/errors/grade_score_out_of_range_rejected
    """
    ctx = setup_scheduled_skills_test(
        skills_pass_threshold=80, classroom_required_hours=0, range_required_hours=0,
        road_required_hours=1)
    resp = api_client.grade_skills_test(
        ctx["test"]["id"],
        {"pre_trip_score": 90, "basic_control_score": 90, "road_score": 150},
        make_examiner_headers(ctx["examiner"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
