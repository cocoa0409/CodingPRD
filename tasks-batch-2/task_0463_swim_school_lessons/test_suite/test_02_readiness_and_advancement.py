"""Assessment readiness scoring (strict vs holistic), the SUBMITTED branch
(approve advances / reject is quiet), advancement gating, and the level-transfer
cascade.

Difficulty queue (A): dual_variant_calc (Assessment), non_linear_state_machine
(Assessment branch), transitive_cascade (assessment approve).
Corner queue (B): state_machines + validations advancement instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_skill_payload,
    create_assessment_payload,
    TEST_USERS,
    make_instructor_headers,
    set_clock,
    create_location,
    create_level,
    create_skill,
    create_instructor,
    create_class_session,
    open_session,
    create_parent,
    create_student,
    setup_parent_with_student,
    create_active_enrollment,
    create_assessment,
    submit_assessment,
    setup_submitted_strict_ready_assessment,
)

ADMIN = TEST_USERS["school_admin_headers"]


def _level1_with_two_skills(clock="2026-01-10T00:00:00Z", next_level=False):
    """Clock + location + Level 1 with two equal-weight skills + certified
    instructor + OPEN session + parent + student + ACTIVE enrollment.

    Returns a dict: level, next_level_id, sk1, sk2, instructor, parent,
    student, enrollment.
    """
    set_clock(clock)
    location = create_location()
    next_level_id = None
    if next_level:
        lvl2 = create_level(
            name="Level 2", sequence_order=2, min_age_months=36,
            max_age_months=200, max_students_per_instructor=6,
            monthly_tuition_cents=13000,
        )
        next_level_id = lvl2["id"]
    lvl_kwargs = dict(
        name="Level 1", sequence_order=1, min_age_months=36, max_age_months=200,
        max_students_per_instructor=4, monthly_tuition_cents=12000,
        readiness_threshold=0.80,
    )
    if next_level_id:
        lvl_kwargs["next_level_id"] = next_level_id
    level = create_level(**lvl_kwargs)
    sk1 = create_skill(level["id"], name="Back Float 10s", weight=1.0)
    sk2 = create_skill(level["id"], name="Front Glide", weight=1.0)
    instructor = create_instructor(certified_level_ids=[level["id"]])
    session = create_class_session(location["id"], level["id"], instructor["id"])
    session = open_session(session["id"])
    parent, student = setup_parent_with_student(level["id"])
    enrollment = create_active_enrollment(parent, student, session)
    return {
        "level": level, "next_level_id": next_level_id, "sk1": sk1, "sk2": sk2,
        "instructor": instructor, "session": session, "parent": parent,
        "student": student, "enrollment": enrollment,
    }


# ─── dual_variant_calc (Assessment): strict vs holistic ────────────────────
def test_holistic_ready_true_on_weighted_average(api):
    """PRD §3.7: "`holistic_ready` is set true exactly when the rounded
    `weighted_score` is at or above the level's `readiness_threshold`."

    Scores 0.90 and 0.70 with equal weights give weighted_score 0.8, which meets
    the 0.80 threshold, so holistic_ready is true.

    Design: Difficulty/dual_variant_calc/readiness_strict_vs_holistic_diverge_on_assessment
    """
    env = _level1_with_two_skills()
    asmt = create_assessment(
        env["instructor"], env["enrollment"]["id"],
        [{"skill_id": env["sk1"]["id"], "score": 0.90},
         {"skill_id": env["sk2"]["id"], "score": 0.70}],
    )
    submitted = submit_assessment(env["instructor"], asmt["id"])
    assert submitted["weighted_score"] == 0.8, (
        f"weighted_score {submitted['weighted_score']}"
    )
    assert submitted["holistic_ready"] is True


def test_strict_ready_false_when_one_skill_submastery(api):
    """PRD §3.7: "`strict_ready` is set true exactly when `mastered_count` equals
    the total number of skills in the assessed level — every single skill
    mastered"
    PRD §3.7: "the strict variant requires every skill mastered, so a single
    sub-mastery skill blocks it even when the weighted average clears the
    threshold"

    Scores 0.90 and 0.70 with mastery 0.80 master only 1 of 2 skills, so
    strict_ready is false even though holistic_ready is true for the same scores.

    Design: Difficulty/dual_variant_calc/readiness_strict_vs_holistic_diverge_on_assessment
    """
    env = _level1_with_two_skills()
    asmt = create_assessment(
        env["instructor"], env["enrollment"]["id"],
        [{"skill_id": env["sk1"]["id"], "score": 0.90},
         {"skill_id": env["sk2"]["id"], "score": 0.70}],
    )
    submitted = submit_assessment(env["instructor"], asmt["id"])
    assert submitted["strict_ready"] is False
    assert submitted["holistic_ready"] is True, (
        "holistic and strict must diverge for identical scores"
    )


# ─── non_linear_state_machine (Assessment branch): reject vs approve ───────
def test_reject_branch_leaves_student_level_unchanged(api):
    """PRD §3.7: "Rejection is the symmetric quiet branch: it moves the
    assessment from `SUBMITTED` to `REJECTED`, has no preconditions, and produces
    no level change and no enrollment mutation — the student remains at the
    assessed level."

    Rejecting a strict_ready SUBMITTED assessment leaves the student's
    current_level_id and the enrollment untouched.

    Design: Difficulty/non_linear_state_machine/assessment_branch_reject_diverges_from_approve
    """
    env = setup_submitted_strict_ready_assessment(next_level=True)
    res = api.reject_assessment(env["assessment"]["id"], ADMIN)
    rejected = validate_success(res, 200)
    assert rejected["status"] == "REJECTED"
    student = validate_success(api.get_student(env["student"]["id"], ADMIN), 200)
    assert student["current_level_id"] == env["level"]["id"], (
        "reject must not advance the student's level"
    )
    enr = validate_success(api.get_enrollment(env["enrollment"]["id"], ADMIN), 200)
    assert enr["status"] == "ACTIVE", "reject must not mutate the enrollment"


def test_approve_branch_advances_student_level(api):
    """PRD §3.7: "A successful approval advances the child: the student's
    `current_level_id` is set to the assessed level's `next_level_id` (the first
    cascade level)"

    Approving the strict_ready SUBMITTED assessment moves the assessment to
    APPROVED and sets the student's current_level_id to the next level —
    diverging from the reject branch on the same fork.

    Design: Difficulty/non_linear_state_machine/assessment_branch_reject_diverges_from_approve
    """
    env = setup_submitted_strict_ready_assessment(next_level=True)
    res = api.approve_assessment(env["assessment"]["id"], ADMIN)
    approved = validate_success(res, 200)
    assert approved["status"] == "APPROVED"
    student = validate_success(api.get_student(env["student"]["id"], ADMIN), 200)
    assert student["current_level_id"] == env["next_level_id"], (
        "approve must advance the student to the next level"
    )


# ─── transitive_cascade (assessment approve) ───────────────────────────────
def test_approve_withdraws_mismatched_enrollment(api):
    """PRD §3.7: "because the child's level changed, every `ACTIVE` or `PAUSED`
    enrollment of that student whose session sits at a level other than the new
    current level is moved to `WITHDRAWN`"

    The student's ACTIVE Level-1 enrollment, now mismatched after advancing to
    Level 2, is withdrawn by the approval cascade.

    Design: Difficulty/transitive_cascade/assessment_approve_advances_then_withdraws_mismatched_enrollment
    """
    env = setup_submitted_strict_ready_assessment(next_level=True)
    validate_success(api.approve_assessment(env["assessment"]["id"], ADMIN), 200)
    student = validate_success(api.get_student(env["student"]["id"], ADMIN), 200)
    assert student["current_level_id"] == env["next_level_id"]
    enr = validate_success(api.get_enrollment(env["enrollment"]["id"], ADMIN), 200)
    assert enr["status"] == "WITHDRAWN", (
        "the level-mismatched enrollment must be withdrawn by the cascade"
    )


def test_approve_issues_level_transfer_disruption_credit(api):
    """PRD §3.7: "for each such disrupted enrollment a makeup credit with reason
    `LEVEL_TRANSFER_DISRUPTION` is issued to the student (the second cascade
    level)."

    The approval cascade that withdraws the mismatched enrollment issues exactly
    one LEVEL_TRANSFER_DISRUPTION credit for the student.

    Design: Difficulty/transitive_cascade/assessment_approve_advances_then_withdraws_mismatched_enrollment
    """
    env = setup_submitted_strict_ready_assessment(next_level=True)
    validate_success(api.approve_assessment(env["assessment"]["id"], ADMIN), 200)
    credits, _ = _list_credits(api, env["student"]["id"])
    transfer = [c for c in credits
                if c["reason"] == "LEVEL_TRANSFER_DISRUPTION"]
    assert len(transfer) == 1, (
        f"expected exactly 1 LEVEL_TRANSFER_DISRUPTION credit, got {len(transfer)}"
    )


def _list_credits(api, student_id):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(
        api.list_makeup_credits(ADMIN, params={"student_id": student_id})
    )


# ─── Corner queue (B): advancement gating + assessment transitions ─────────
def test_approve_without_next_level_rejected(api):
    """PRD §3.7: "the assessed level must have a non-null `next_level_id`, or the
    approval is rejected with `ERR_NO_NEXT_LEVEL`."

    A strict_ready SUBMITTED assessment on a top level (next_level_id null) is
    rejected with ERR_NO_NEXT_LEVEL.

    Design: Corner/validations/approve_without_next_level_returns_no_next_level
    """
    env = setup_submitted_strict_ready_assessment(next_level=False)
    res = api.approve_assessment(env["assessment"]["id"], ADMIN)
    validate_error(res, "ERR_NO_NEXT_LEVEL")


def test_approve_not_strict_ready_rejected(api):
    """PRD §3.7: "`strict_ready` must be true, or the approval is rejected with
    `ERR_NOT_READY_TO_ADVANCE`"

    An assessment scored 1.0 and 0.5 (one skill below mastery) is not
    strict_ready, so approval is rejected ERR_NOT_READY_TO_ADVANCE even though a
    next level exists.

    Design: Corner/validations/approve_not_ready_returns_not_ready_to_advance
    """
    env = _level1_with_two_skills(next_level=True)
    asmt = create_assessment(
        env["instructor"], env["enrollment"]["id"],
        [{"skill_id": env["sk1"]["id"], "score": 1.0},
         {"skill_id": env["sk2"]["id"], "score": 0.5}],
    )
    submit_assessment(env["instructor"], asmt["id"])
    res = api.approve_assessment(asmt["id"], ADMIN)
    validate_error(res, "ERR_NOT_READY_TO_ADVANCE")


def test_approve_draft_assessment_rejected(api):
    """PRD §3.7: "Either decision requires the assessment to be in `SUBMITTED`;
    attempting to approve or reject one that is not yields
    `ERR_ASSESSMENT_NOT_SUBMITTED`."

    Approving a still-DRAFT (never submitted) assessment is rejected
    ERR_ASSESSMENT_NOT_SUBMITTED.

    Design: Corner/state_machines/approve_draft_assessment_returns_assessment_not_submitted
    """
    env = _level1_with_two_skills(next_level=True)
    # Single-skill assessment is created in DRAFT but never submitted.
    asmt = create_assessment(
        env["instructor"], env["enrollment"]["id"],
        [{"skill_id": env["sk1"]["id"], "score": 1.0},
         {"skill_id": env["sk2"]["id"], "score": 1.0}],
    )
    res = api.approve_assessment(asmt["id"], ADMIN)
    validate_error(res, "ERR_ASSESSMENT_NOT_SUBMITTED")


def test_submit_skill_set_mismatch_rejected(api):
    """PRD §3.7: "the submitted `skill_scores` must cover exactly the assessed
    level's skill set — no missing skill, no extra skill — or the submission is
    rejected with `ERR_SKILL_SET_MISMATCH`."

    Submitting an assessment that scores only one of the level's two skills is
    rejected ERR_SKILL_SET_MISMATCH.

    Design: Corner/validations/skill_set_mismatch_blocks_submit
    """
    env = _level1_with_two_skills(clock="2026-01-05T00:00:00Z")
    asmt = create_assessment(
        env["instructor"], env["enrollment"]["id"],
        [{"skill_id": env["sk1"]["id"], "score": 1.0}],
    )
    instr_headers = make_instructor_headers(env["instructor"]["id"])
    res = api.submit_assessment(asmt["id"], instr_headers)
    validate_error(res, "ERR_SKILL_SET_MISMATCH")
