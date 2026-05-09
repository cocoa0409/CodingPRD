"""Degree-plan gap analysis, recommendations, and transferable credits (PRD §3.8).

Per the per-instance Difficulty design and PRD §3.8 the per-course-rounded-then-summed
order for transferable_credits is pinned: 0.625 → round to 0.63 per course, then sum.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, TEST_USERS,
)
from test_helpers.fixtures import (
    setup_basic_world, setup_open_offering, advance_clock,
    setup_two_program_world_with_completed_source_course,
    create_credit_equivalence_policy, get_degree_plan,
    create_course, create_offering, create_student,
    submit_enrollment_success, list_waitlist,
)


def test_degree_plan_completed_credits_reflects_completed_courses(api, registrar_headers):
    """PRD §3.8: "completed_credits, the sum of Course.credits across every
    course_id in the student's completed_course_ids."

    Claim: a student with one completed 3.0-credit course shows
    completed_credits == 3.00 in the degree plan.
    """
    world = setup_basic_world(student_year=1)
    completed_course = create_course(world["department"]["id"], credits=3.0)
    # The student was created without any completed courses; create a new
    # student that has the completed_course recorded directly.
    student = create_student(
        world["department"]["id"], world["campus"]["id"], year_in_program=1,
        completed_course_ids=[completed_course["id"]],
    )
    plan = get_degree_plan(student["id"])
    assert float(plan["completed_credits"]) == pytest.approx(3.0, abs=0.01)


def test_degree_plan_in_progress_credits_includes_waitlisted(api, registrar_headers):
    """PRD §3.8: "in_progress_credits, the sum of Course.credits across every
    EnrollmentRequest for this student whose academic_status is APPROVED,
    WAITLISTED, or SETTLED. This is intentionally a ceiling estimate:
    waitlisted courses are included so a student can see the worst-case
    credit load they have committed to, even though a waitlisted seat may
    not materialize."

    Claim: a student with one APPROVED 3.0-credit enrollment AND one
    WAITLISTED 3.0-credit enrollment shows in_progress_credits == 6.00.
    """
    world = setup_basic_world(student_year=2)
    # Approved enrollment.
    co_a = setup_open_offering(world, credits=3.0,
                                scheduled_meetings=[{"day_of_week": 0, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    er_a = submit_enrollment_success(world["student"], co_a["offering"]["id"])
    assert er_a["academic_status"] == "APPROVED"

    # Waitlisted enrollment. Pick a non-overlapping slot so the
    # priority-8 time-conflict check does not pre-empt the seat decision —
    # co_a above sits on day 0, 540-600.
    from test_helpers.fixtures import setup_offering_with_seat_taken
    full = setup_offering_with_seat_taken(
        world, credits=3.0,
        scheduled_meetings=[{"day_of_week": 3, "start_minute_of_day": 540, "end_minute_of_day": 660}],
    )
    er_w = submit_enrollment_success(world["student"], full["offering"]["id"])
    assert er_w["academic_status"] == "WAITLISTED"

    plan = get_degree_plan(world["student"]["id"])
    assert float(plan["in_progress_credits"]) == pytest.approx(6.0, abs=0.01)


def test_degree_plan_gap_excludes_waitlisted(api, registrar_headers):
    """PRD §3.8: "gap_courses, the set of required course identifiers minus
    the student's completed_course_ids minus every offering's course_id for
    which the student has an enrollment in APPROVED or SETTLED (waitlisted
    enrollments are not subtracted here, because a waitlisted seat is not yet
    held)."

    Claim: a course the student is only WAITLISTED for is still in
    gap_courses (gap_count includes it).
    """
    world = setup_basic_world(student_year=2)
    # All department-owned courses are required by PRD §3.8 by construction.
    from test_helpers.fixtures import setup_offering_with_seat_taken
    full = setup_offering_with_seat_taken(world)
    er = submit_enrollment_success(world["student"], full["offering"]["id"])
    assert er["academic_status"] == "WAITLISTED"
    plan = get_degree_plan(world["student"]["id"])
    # The waitlisted course's underlying course_id is full["course"]["id"]; the
    # course is owned by the home dept, so it is in the required-set. Since
    # WAITLISTED does NOT subtract from gap_courses, the course_id must still
    # be enumerated as a gap.
    assert full["course"]["id"] in plan["gap_courses"], (
        f"Expected waitlisted course in gap_courses; got {plan['gap_courses']}"
    )


def test_recommendations_returns_at_most_top_k(api, registrar_headers):
    """PRD §3.8: "The system returns the top five candidates by recommendation
    score in descending order, with the offering's id ascending as the
    tie-break."

    Claim: when more than five OPEN gap-course offerings exist for the
    student's next-open term, the response contains at most five rows.
    """
    world = setup_basic_world(student_year=1)
    # Create six gap-course offerings.
    from test_helpers.fixtures import open_offering
    for i in range(6):
        course = create_course(world["department"]["id"], credits=3.0,
                                code_prefix=f"REC{i:02d}")
        offering = create_offering(
            term_id=world["term"]["id"], course_id=course["id"],
            campus_id=world["campus"]["id"], instructor_id=world["instructor"]["id"],
            base_capacity=5,
            scheduled_meetings=[{"day_of_week": i % 7, "start_minute_of_day": 800 + i * 5, "end_minute_of_day": 830 + i * 5}],
        )
        open_offering(offering["id"])

    res = api.get_student_recommendations(world["student"]["id"], registrar_headers)
    body = res.json()
    assert res.status_code == 200
    data = body["data"]
    assert isinstance(data, list)
    assert len(data) <= 5


def test_transferable_credits_per_course_then_sum_pinned_to_one_dot_two_six(api, registrar_headers):
    """PRD §3.8: "the system computes a per-course transferable value equal
    to that course's credits multiplied by the policy's transfer_factor,
    rounded half-up to two decimal places per course before summation. The
    transferable credits figure is then the sum of those per-course rounded
    values. The per-course-then-sum order is pinned: rounding the sum after
    the multiplication would in general produce a different total in cents,
    and would also be sensitive to course iteration order when the rounding
    boundary fell exactly between two summation paths."

    Claim: with two policies on the same source course (credits=1.0,
    transfer_factor=0.625) the per-course-rounded values are 0.63 + 0.63 =
    1.26. Sum-then-round would give 1.25.

    # difficulty: dual_variant_calc/dual_variant_transferable_credits_policy_domain
    # difficulty: combinatorial_formula/combinatorial_transferable_credits_rounding_mode_b
    """
    cw = setup_two_program_world_with_completed_source_course()
    # source_program_id must equal the source course's "owning program" (per PRD §3.8);
    # the only identifier a Course carries that maps to a program is owning_department_id,
    # so the policy uses d_src["id"]. target_program_id must equal student.program_id.
    create_credit_equivalence_policy(
        source_program_id=cw["d_src"]["id"],
        target_program_id=cw["tgt_program_id"],
        source_course_id=cw["c_src"]["id"],
        target_course_id=cw["c_tgt"]["id"],
        transfer_factor=0.625,
    )
    # Policy 2 (same source course, different target course)
    create_credit_equivalence_policy(
        source_program_id=cw["d_src"]["id"],
        target_program_id=cw["tgt_program_id"],
        source_course_id=cw["c_src"]["id"],
        target_course_id=cw["c_tgt2"]["id"],
        transfer_factor=0.625,
    )
    plan = get_degree_plan(cw["student"]["id"])
    assert "transferable_credits" in plan
    # Expected: per-course rounding then sum: round(0.625, 2) + round(0.625, 2) = 0.63 + 0.63 = 1.26.
    # If the implementation summed first (0.625+0.625=1.25) then rounded, it would yield 1.25.
    assert float(plan["transferable_credits"]) == pytest.approx(1.26, abs=0.005)


def test_transferable_credits_zero_when_no_policy_then_changes_after_policy_added(api, registrar_headers):
    """PRD §3.8: "Because the calculation is read-time, the figure surfaced
    through the student-facing degree plan reflects the current policy values;
    it is not frozen until term conclusion."

    Claim: GET /degree-plan returns transferable_credits=0 before any policy
    matches; after adding two matching policies (each 0.625), the same call
    returns 1.26.

    # difficulty: dual_variant_calc/dual_variant_transferable_credits_policy_domain
    """
    cw = setup_two_program_world_with_completed_source_course()
    # No policies yet.
    plan_before = get_degree_plan(cw["student"]["id"])
    assert float(plan_before["transferable_credits"]) == pytest.approx(0.0, abs=0.005)

    create_credit_equivalence_policy(
        source_program_id=cw["d_src"]["id"],
        target_program_id=cw["tgt_program_id"],
        source_course_id=cw["c_src"]["id"],
        target_course_id=cw["c_tgt"]["id"],
        transfer_factor=0.625,
    )
    create_credit_equivalence_policy(
        source_program_id=cw["d_src"]["id"],
        target_program_id=cw["tgt_program_id"],
        source_course_id=cw["c_src"]["id"],
        target_course_id=cw["c_tgt2"]["id"],
        transfer_factor=0.625,
    )
    plan_after = get_degree_plan(cw["student"]["id"])
    assert float(plan_after["transferable_credits"]) == pytest.approx(1.26, abs=0.005)
