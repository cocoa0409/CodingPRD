"""Grading, GPA, academic standing, transcript scoping, and degree audit.

Translates Difficulty queue dual_variant_calc (GPA cumulative vs term),
combinatorial_formula (credit-weighted nonlinear GPA), non_linear_state_machine
(parallel registration x grade axis), plus Corner calculations instances
(W excluded, probation, rounding, degree audit).
"""
import pytest

from test_helpers import (
    validate_success,
    TEST_USERS,
)
from test_helpers import fixtures as fx

REG = TEST_USERS["registrar_headers"]


def test_gpa_cumulative_vs_term_scope(api):
    """PRD §3.8: "divide the total quality points by the total credit hours,
    rounding half up to two decimal places."
    PRD §3.9: "When scoped to a single term by a `term_id` query parameter, the
    `term_gpa` uses the same credit-hour-weighted formula but restricts the
    considered set to enrollments in that term; the `cumulative_gpa` spans every
    term."

    Term A holds A(4cr)+B(3cr); Term B holds F(3cr). The cumulative considered set
    spans both terms: (4*4 + 3*3 + 0*3)/(4+3+3) = 25/10 = 2.50. The Term-A-scoped
    set restricts to that term's two graded enrollments: (4*4 + 3*3)/(4+3) = 25/7
    = 3.5714... -> 3.57 (round_half_up). The two scopes diverge — same weighting
    formula, different considered set.

    Design: Difficulty/dual_variant_calc/gpa_cumulative_vs_term_scope
    """
    term_a = fx.setup_graded_student(
        [(4, "A"), (3, "B")],
        term_overrides={"name": "Term A",
                        "registration_opens_at": "2025-08-01T00:00:00Z",
                        "add_deadline": "2025-09-01T00:00:00Z",
                        "drop_deadline": "2025-09-15T00:00:00Z",
                        "withdraw_deadline": "2025-10-15T00:00:00Z"},
        clock="2025-08-10T00:00:00Z",
    )
    # Second term for the SAME student: F(3cr).
    student = term_a["student"]
    prog = term_a["program"]
    instr = term_a["instructor"]
    term_b = fx.make_term(name="Term B")
    cf = fx.make_course(prog["id"], credit_hours=3)
    sec_b = fx.make_section(term_b["id"], cf["id"], instr["id"],
                            meeting_days="MWF", meeting_start_min=540, meeting_end_min=590)
    fx.advance_term(term_b["id"], "REGISTRATION_OPEN")
    fx.make_appointment(term_b["id"], student["id"], max_credit_hours=18)
    fx.set_clock(fx.CLOCK_REGISTRATION)
    enr_b = fx.enroll(term_b["id"], sec_b["id"], student["id"])
    fx.advance_term(term_b["id"], "IN_SESSION")
    fx.grade(enr_b["id"], "F")

    stu_final = validate_success(api.get_student(student["id"], REG), 200)
    assert stu_final["gpa"] == 2.50, f"cumulative gpa should be 2.50, got {stu_final['gpa']}"

    transcript = validate_success(
        api.get_transcript(student["id"], REG, params={"term_id": term_a["term"]["id"]}), 200
    )
    # Term A scope excludes Term B's F: (16+9)/7 = 3.57, distinct from the 2.50
    # cumulative — the two scopes diverge as the dual-variant rule requires.
    assert transcript["term_gpa"] == 3.57, f"Term A term_gpa should be 3.57, got {transcript['term_gpa']}"
    assert transcript["term_gpa"] != stu_final["gpa"], "term and cumulative scopes must diverge"


def test_term_gpa_isolates_single_term_via_transcript(api):
    """PRD §3.9: "When scoped to a single term by a `term_id` query parameter, the
    `term_gpa` uses the same credit-hour-weighted formula but restricts the
    considered set to enrollments in that term; the `cumulative_gpa` spans every
    term."

    A second probe of the cumulative-vs-term dual scope, reading both figures off
    one transcript: with a single graded term holding A(4cr)+B(3cr), the
    term-scoped term_gpa equals the cumulative_gpa (both 2.50) — the same formula,
    same considered set when only one term exists.

    Design: Difficulty/dual_variant_calc/gpa_cumulative_vs_term_scope
    """
    res = fx.setup_graded_student([(4, "A"), (3, "B")])  # (16+9)/7 = 3.5714 -> 3.57
    transcript = validate_success(
        api.get_transcript(res["student"]["id"], REG, params={"term_id": res["term"]["id"]}), 200
    )
    assert transcript["term_gpa"] == 3.57, f"term_gpa should be 3.57, got {transcript['term_gpa']}"
    assert transcript["cumulative_gpa"] == 3.57, (
        f"cumulative spans every term; with one term it equals term_gpa, "
        f"got {transcript['cumulative_gpa']}"
    )


def test_gpa_credit_weighted_nonlinear(api):
    """PRD §3.8: "For each considered enrollment, multiply its `grade_points` by
    its course's `credit_hours` to get its quality points; sum the quality points
    across the considered set, sum the course credit hours across the considered
    set, and divide the total quality points by the total credit hours".
    PRD §3.8: "An `F` contributes zero quality points but its credit hours still
    enter the denominator (failed but attempted)".

    A(4cr)+B(3cr)+F(3cr) = (16+9+0)/(4+3+3) = 2.50, not the unweighted mean.

    Design: Difficulty/combinatorial_formula/gpa_credit_weighted_nonlinear
    """
    res = fx.setup_graded_student([(4, "A"), (3, "B"), (3, "F")])
    stu = validate_success(api.get_student(res["student"]["id"], REG), 200)
    assert stu["gpa"] == 2.50, f"credit-weighted gpa should be 2.50, got {stu['gpa']}"
    assert stu["earned_credit_hours"] == 7, f"earned should be 4+3 (F not passing), got {stu['earned_credit_hours']}"
    assert stu["academic_standing"] == "GOOD"


def test_gpa_weighting_favors_higher_credit_course(api):
    """PRD §3.8: "For each considered enrollment, multiply its `grade_points` by
    its course's `credit_hours` to get its quality points; sum the quality points
    across the considered set, sum the course credit hours across the considered
    set, and divide the total quality points by the total credit hours".

    A second probe of credit-weighting: A(1cr)+C(5cr) = (4+10)/6 = 2.3333 -> 2.33,
    pulled toward the 5-credit C and away from the unweighted mean of 3.0.

    Design: Difficulty/combinatorial_formula/gpa_credit_weighted_nonlinear
    """
    res = fx.setup_graded_student([(1, "A"), (5, "C")])
    stu = validate_success(api.get_student(res["student"]["id"], REG), 200)
    assert stu["gpa"] == 2.33, f"credit-weighted gpa should be 2.33, got {stu['gpa']}"


def test_grade_entry_advances_grade_axis_only(api):
    """PRD §3.8: "On success the `grade_status` advances `UNGRADED → GRADED` while
    `registration_status` stays `ENROLLED`; the enrollment's `grade_points` are
    set from the letter grade on a 4.0 scale where `A` is 4.0, `B` is 3.0, `C` is
    2.0, `D` is 1.0, and `F` is 0.0".

    Design: Difficulty/non_linear_state_machine/enrollment_parallel_registration_x_grade
    """
    base = fx.setup_one_enrolled_student(credit_hours=3)
    fx.advance_term(base["term"]["id"], "IN_SESSION")
    graded = fx.grade(base["enrollment"]["id"], "B")
    assert graded["grade_status"] == "GRADED"
    assert graded["registration_status"] == "ENROLLED"
    assert graded["grade_points"] == 3.0


def test_grade_points_map_for_grade_d(api):
    """PRD §3.8: "the enrollment's `grade_points` are set from the letter grade on
    a 4.0 scale where `A` is 4.0, `B` is 3.0, `C` is 2.0, `D` is 1.0, and `F` is
    0.0".

    A second distinct grade-axis transition: a D maps to 1.0 grade points while
    registration_status stays ENROLLED.

    Design: Difficulty/non_linear_state_machine/enrollment_parallel_registration_x_grade
    """
    base = fx.setup_one_enrolled_student(credit_hours=3)
    fx.advance_term(base["term"]["id"], "IN_SESSION")
    graded = fx.grade(base["enrollment"]["id"], "D")
    assert graded["grade_status"] == "GRADED"
    assert graded["registration_status"] == "ENROLLED"
    assert graded["grade_points"] == 1.0


def test_withdrawn_w_excluded_from_gpa(api):
    """PRD §3.8: "withdrawals carrying a `W` and ungraded enrollments are excluded
    entirely."
    PRD §3.8: "whereas a `W` enters neither numerator nor denominator."

    One graded A(3cr) plus one WITHDRAWN section: gpa 4.00.

    Design: Corner/calculations/withdrawn_w_excluded_from_gpa
    """
    prog = fx.make_program()
    instr = fx.make_instructor()
    term = fx.make_term()
    ca = fx.make_course(prog["id"], credit_hours=3)
    cw = fx.make_course(prog["id"], credit_hours=3)
    sa = fx.make_section(term["id"], ca["id"], instr["id"],
                         meeting_days="MWF", meeting_start_min=540, meeting_end_min=590)
    sw = fx.make_section(term["id"], cw["id"], instr["id"],
                         meeting_days="TR", meeting_start_min=600, meeting_end_min=650)
    fx.advance_term(term["id"], "REGISTRATION_OPEN")
    stu, _ = fx.setup_student_ready(term["id"], prog["id"])
    fx.set_clock(fx.CLOCK_REGISTRATION)
    ea = fx.enroll(term["id"], sa["id"], stu["id"])
    ew = fx.enroll(term["id"], sw["id"], stu["id"])
    fx.advance_term(term["id"], "IN_SESSION")
    fx.grade(ea["id"], "A")
    fx.set_clock("2026-02-20T00:00:00Z")  # partial/withdraw window
    fx.withdraw(ew["id"], stu["id"])

    stu_final = validate_success(api.get_student(stu["id"], REG), 200)
    assert stu_final["gpa"] == 4.00, f"W must not affect gpa, got {stu_final['gpa']}"
    assert stu_final["earned_credit_hours"] == 3


def test_probation_standing_from_failing_gpa(api):
    """PRD §3.8: "Academic standing follows from cumulative GPA: `GOOD` when the
    GPA is at least 2.00, `WARNING` when the GPA is at least 1.00 but below 2.00,
    and `PROBATION` when the GPA is below 1.00."

    A student whose only graded course is an F (gpa 0.00) is PROBATION.

    Design: Corner/calculations/probation_standing_from_failing_gpa
    """
    res = fx.setup_graded_student([(3, "F")])
    stu = validate_success(api.get_student(res["student"]["id"], REG), 200)
    assert stu["gpa"] == 0.00
    assert stu["academic_standing"] == "PROBATION"
    assert stu["earned_credit_hours"] == 0


def test_gpa_rounding_half_up(api):
    """PRD §2.7: "it is reported on a 4.0 scale rounded half up to exactly two
    decimal places."
    PRD §3.8: "divide the total quality points by the total credit hours, rounding
    half up to two decimal places."

    B(3cr)+C(4cr) = (9+8)/7 = 2.42857... rounds half up to 2.43.

    Design: Corner/calculations/gpa_rounding_half_up
    """
    res = fx.setup_graded_student([(3, "B"), (4, "C")])
    stu = validate_success(api.get_student(res["student"]["id"], REG), 200)
    assert stu["gpa"] == 2.43, f"round_half_up(17/7) should be 2.43, got {stu['gpa']}"


def test_degree_audit_credits_remaining_and_completion(api):
    """PRD §3.9: "It reports the program's `required_credit_hours`, the student's
    `earned_credit_hours`, the `credits_remaining` (the required total minus
    earned, never below zero), a `gpa_ok` flag that is true when the student's
    cumulative `gpa` is at least the program's `min_gpa`, the `is_complete` flag
    that is true only when no credits remain and the GPA requirement is met".

    completed 110 + earned A(4cr)+B(3cr)=7 -> earned 117, remaining 3, gpa_ok true,
    is_complete false.

    Design: Corner/calculations/degree_audit_credits_remaining_and_completion
    """
    prog = fx.make_program()  # required 120, min_gpa 2.0
    instr = fx.make_instructor()
    term = fx.make_term()
    c4 = fx.make_course(prog["id"], credit_hours=4)
    c3 = fx.make_course(prog["id"], credit_hours=3)
    s4 = fx.make_section(term["id"], c4["id"], instr["id"],
                         meeting_days="MWF", meeting_start_min=540, meeting_end_min=590)
    s3 = fx.make_section(term["id"], c3["id"], instr["id"],
                         meeting_days="TR", meeting_start_min=600, meeting_end_min=650)
    fx.advance_term(term["id"], "REGISTRATION_OPEN")
    stu, _ = fx.setup_student_ready(term["id"], prog["id"], max_credit_hours=18,
                                    student_overrides={"completed_credit_hours": 110})
    fx.set_clock(fx.CLOCK_REGISTRATION)
    e4 = fx.enroll(term["id"], s4["id"], stu["id"])
    e3 = fx.enroll(term["id"], s3["id"], stu["id"])
    fx.advance_term(term["id"], "IN_SESSION")
    fx.grade(e4["id"], "A")
    fx.grade(e3["id"], "B")

    audit = validate_success(api.get_degree_audit(stu["id"], REG), 200)
    assert audit["earned_credit_hours"] == 117
    assert audit["credits_remaining"] == 3
    assert audit["gpa_ok"] is True
    assert audit["is_complete"] is False
