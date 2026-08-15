"""Calculation claims: GPA input-set filtering, the W-grade variant divergence
between the two transcripts, and placement recency (PRD 3.2, 3.5, 3.8)."""
import pytest

from test_helpers import (
    CLOCK_AFTER_COLLEGE_END,
    CLOCK_IN_MISMATCH_WINDOW,
    ApiErrorId,
    confirm_enrollment,
    confirm_enrollment_raw,
    create_course,
    create_enrollment,
    create_offering,
    create_placement_record,
    credential_course,
    finalize_offering,
    get_student,
    list_transcript_entries_for_enrollment,
    make_registrar_headers,
    move_offering_to_grading,
    open_offering,
    register_student,
    set_clock,
    setup_base,
    setup_graded_scenario,
    submit_grade,
    validate_error,
    validate_success,
    withdraw_enrollment,
)

REGISTRAR = make_registrar_headers()


def test_gpa_input_set_excludes_pending_and_voided(api):
    """PRD 3.8: "The GPA recompute runs over all of the student's `POSTED` entries
    only; `PENDING` and `VOIDED` entries are excluded."
    PRD 3.8: "The registrar may also void a `POSTED` entry, moving it to `VOIDED` —
    used when a grade is under appeal or correction — and the GPA is recomputed
    again with the voided entry excluded from both numerator and denominator."
    PRD 3.8: "When the eligible set is empty the GPA is 0.000."

    Design: Corner/calculations/gpa_input_set_excludes_pending_and_voided
    """
    ctx = setup_graded_scenario(grade="A")
    college_entry = list_transcript_entries_for_enrollment(
        ctx["enrollment"]["id"], institution="COLLEGE"
    )[0]
    hs_entry = list_transcript_entries_for_enrollment(
        ctx["enrollment"]["id"], institution="HIGH_SCHOOL"
    )[0]

    validate_success(api.post_transcript_entry(college_entry["id"], REGISTRAR))
    mid = get_student(ctx["student"]["id"])
    assert mid["college_gpa"] == pytest.approx(4.0, abs=1e-9), (
        f"12 points / 3 hours from the POSTED college entry must give 4.000, got "
        f"{mid['college_gpa']}"
    )
    assert mid["hs_gpa"] == pytest.approx(0.0, abs=1e-9), (
        f"The still-PENDING high-school entry is excluded: hs_gpa must stay 0.000, "
        f"got {mid['hs_gpa']}"
    )
    assert hs_entry["status"] == "PENDING"

    validate_success(api.void_transcript_entry(college_entry["id"], REGISTRAR))
    end = get_student(ctx["student"]["id"])
    assert end["college_gpa"] == pytest.approx(0.0, abs=1e-9), (
        f"After voiding the only POSTED entry the eligible set is empty: "
        f"college_gpa must return to 0.000 with no residual drift, got "
        f"{end['college_gpa']}"
    )


def test_gpa_w_included_hs_excluded_college(api):
    """PRD 3.8: "The college variant writes `college_gpa` and uses a 4.0 scale —
    `A` is 4, `B` is 3, `C` is 2, `D` is 1, `F` is 0 — with `W` excluded from
    numerator and denominator entirely, so a `W` does not move the college GPA."
    PRD 3.8: "The high school variant writes `hs_gpa` and uses a dual-credit
    weighted 5.0 scale — `A` is 5, `B` is 4, `C` is 3, `D` is 2, `F` is 0, `W` is
    0 — with `W` included at 0 points and its `credit_value` counted in the
    denominator, so a `W` drags the high school GPA down."
    PRD 3.8: "A `WITHDRAWN` enrollment always produces a `COLLEGE` `PENDING` entry
    with grade `W`, and produces a `HIGH_SCHOOL` `PENDING` entry with grade `W`
    only when its `withdrawn_at` is strictly after the high school term's
    `drop_deadline` — a withdraw that happened before the high school's drop
    deadline leaves no record on the high school transcript."

    Design: Corner/calculations/gpa_w_included_hs_excluded_college
    """
    ctx = setup_base(
        course_overrides={
            "course_code": "MATH151",
            "title": "College Algebra",
            "placement_exam_code": "NONE",
            "min_placement_score": 0,
        }
    )
    course_b = create_course(course_code="HIST210", title="US History")
    credential_course(ctx["instructor"]["id"], course_b["id"], qualification_summary="MA History")
    offering_b = create_offering(
        course_b["id"],
        ctx["college_term"]["id"],
        ctx["hs_term"]["id"],
        ctx["school"]["id"],
        ctx["instructor"]["id"],
        capacity=2,
    )
    open_offering(offering_b["id"])

    # Enroll the same student in both offerings and confirm each.
    # register_student already creates the PENDING_VERIFICATION enrollment on
    # ctx["offering"] (PRD 3.5 rejects a second one as ERR_DUPLICATE_ENROLLMENT).
    pair = register_student(ctx)
    student = pair["student"]
    enr_a = confirm_enrollment(ctx["offering"]["id"], pair["enrollment"]["id"])
    enr_b = create_enrollment(student["id"], offering_b["id"])
    enr_b = confirm_enrollment(offering_b["id"], enr_b["id"])
    assert enr_a["status"] == "REGISTERED" and enr_b["status"] == "REGISTERED"

    # Withdraw from offering B inside the mismatch window (after HS drop 09-10,
    # at/before college drop 09-15), so the W posts to both transcripts.
    set_clock(CLOCK_IN_MISMATCH_WINDOW)
    withdrawn = withdraw_enrollment(enr_b["id"])
    assert withdrawn["status"] == "WITHDRAWN" and withdrawn["grade"] == "W"

    # Complete offering A with an A; finalize both offerings.
    move_offering_to_grading(ctx["offering"]["id"])
    submit_grade(enr_a["id"], "A", ctx["instructor"]["id"])
    finalize_offering(ctx["offering"]["id"])
    move_offering_to_grading(offering_b["id"])
    finalize_offering(offering_b["id"])

    te_ac = list_transcript_entries_for_enrollment(enr_a["id"], institution="COLLEGE")[0]
    te_ah = list_transcript_entries_for_enrollment(enr_a["id"], institution="HIGH_SCHOOL")[0]
    te_bc = list_transcript_entries_for_enrollment(enr_b["id"], institution="COLLEGE")[0]
    te_bh = list_transcript_entries_for_enrollment(enr_b["id"], institution="HIGH_SCHOOL")[0]
    assert te_bc["grade"] == "W" and te_bh["grade"] == "W", (
        "Withdrawn at 2026-09-12, strictly after the HS drop deadline 2026-09-10, "
        "the W must post to both transcripts"
    )
    for entry in (te_ac, te_ah, te_bc, te_bh):
        validate_success(api.post_transcript_entry(entry["id"], REGISTRAR))

    student_after = get_student(student["id"])
    assert student_after["college_gpa"] == pytest.approx(4.0, abs=1e-9), (
        f"College variant excludes W entirely: 12/3 == 4.000, got "
        f"{student_after['college_gpa']}"
    )
    assert student_after["hs_gpa"] == pytest.approx(2.5, abs=1e-9), (
        f"HS variant includes W as 0 with units in the denominator: "
        f"(5.0 + 0)/(1.0 + 1.0) == 2.500, got {student_after['hs_gpa']}"
    )


def test_placement_recency_expired_falls_back(api):
    """PRD 3.5: "Placement, checked only when the course's `min_placement_score` is
    greater than 0, means: among the student's non-expired `PlacementRecord` rows
    for the course's `placement_exam_code`, there is at least one (else
    `ERR_PLACEMENT_MISSING`); the latest such record — ordered by `taken_at`
    descending, then `created_at` descending — has a `score` at least the course's
    `min_placement_score` (else `ERR_PLACEMENT_SCORE_INSUFFICIENT`)."
    PRD 3.5: "An expired newer record does not mask an older still-valid record;
    the older record is the one evaluated."
    PRD 3.2: "A record at or past its `expires_at` is invisible to the placement
    check."

    Design: Corner/calculations/placement_recency_expired_falls_back
    """
    ctx = setup_base(
        course_overrides={
            "course_code": "MATH151",
            "title": "College Algebra",
            "placement_exam_code": "MATH",
            "min_placement_score": 70,
        }
    )
    # s1: newest record (score 40, taken 2024-06-01) expired 2026-05-31 < the
    # 2026-08-01 default clock; the older valid 90 carries the confirm.
    pair1 = register_student(ctx, full_name="Alpha One", grade_level=11)
    create_placement_record(pair1["student"]["id"], score=90, taken_at="2026-07-01T00:00:00Z")
    create_placement_record(pair1["student"]["id"], score=40, taken_at="2024-06-01T00:00:00Z")
    # s2: both records valid; the latest (score 40) shadows the older 90.
    pair2 = register_student(ctx, full_name="Beta Two", grade_level=12)
    create_placement_record(pair2["student"]["id"], score=90, taken_at="2026-07-01T00:00:00Z")
    create_placement_record(pair2["student"]["id"], score=40, taken_at="2026-07-15T00:00:00Z")

    confirmed = confirm_enrollment(ctx["offering"]["id"], pair1["enrollment"]["id"])
    assert confirmed["status"] == "REGISTERED", (
        f"The expired 40-score record is invisible; the valid 90 must carry the "
        f"confirm, got {confirmed['status']}"
    )

    response = confirm_enrollment_raw(ctx["offering"]["id"], pair2["enrollment"]["id"])
    validate_error(response, ApiErrorId.ERR_PLACEMENT_SCORE_INSUFFICIENT.value)
