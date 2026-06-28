"""Cross-entity recomputations, cascades, and the score-improvement guarantee.

These helpers are shared by multiple state machines (cohort conclude/cancel,
enrollment cancel/activate, installment default, practice scoring, guarantee
adjudication). Per PRD §2.4, every recomputation that changes a stored value is
a mutation: it refreshes updated_at and bumps version on the owning resource.
"""
from datetime import timedelta

import db


# ---------------------------------------------------------------------------
# Derived-count recomputations
# ---------------------------------------------------------------------------

def recompute_seats_committed(cohort):
    """seats_committed = count of this cohort's enrollments in {ACTIVE, COMPLETED}.

    (scaffold Cohort.seats_committed / PRD §3.1). Recompute is a mutation.
    """
    count = sum(
        1
        for e in db.enrollments.values()
        if e["cohort_id"] == cohort["id"] and e["status"] in ("ACTIVE", "COMPLETED")
    )
    if cohort["seats_committed"] != count:
        cohort["seats_committed"] = count
        db.touch(cohort)


def recompute_active_cohort_count(instructor):
    """active_cohort_count = cohorts in {SCHEDULED, IN_SESSION} assigned here."""
    count = sum(
        1
        for c in db.cohorts.values()
        if c["instructor_id"] == instructor["id"]
        and c["status"] in ("SCHEDULED", "IN_SESSION")
    )
    if instructor["active_cohort_count"] != count:
        instructor["active_cohort_count"] = count
        db.touch(instructor)


def recompute_practice_aggregates(enrollment):
    """completed_practice_count + best_practice_score over COMPLETED PRACTICE
    attempts (scaffold Enrollment fields / PRD §3.5). VOIDED attempts excluded.
    """
    scores = [
        a["scaled_score"]
        for a in db.practice_attempts.values()
        if a["enrollment_id"] == enrollment["id"]
        and a["attempt_type"] == "PRACTICE"
        and a["status"] == "COMPLETED"
    ]
    new_count = len(scores)
    new_best = max(scores) if scores else None
    changed = (
        enrollment["completed_practice_count"] != new_count
        or enrollment["best_practice_score"] != new_best
    )
    enrollment["completed_practice_count"] = new_count
    enrollment["best_practice_score"] = new_best
    if changed:
        db.touch(enrollment)


# ---------------------------------------------------------------------------
# Seat / waitlist helpers
# ---------------------------------------------------------------------------

def held_seat_count(cohort):
    """Outstanding non-waitlisted PENDING_PAYMENT holds on this cohort.

    Used by the seat-vs-waitlist branch (PRD §3.4): full iff seats_committed +
    holds >= seat_capacity.
    """
    return sum(
        1
        for e in db.enrollments.values()
        if e["cohort_id"] == cohort["id"] and e["status"] == "PENDING_PAYMENT"
    )


def promote_waitlist(cohort):
    """Promote the lowest-waitlist_seq WAITLISTED enrollment to PENDING_PAYMENT.

    (PRD §3.4 waitlist promotion). Clears waitlist_seq; the promoted enrollment
    now occupies a held seat awaiting payment. No-op when none are waitlisted.
    """
    waitlisted = [
        e
        for e in db.enrollments.values()
        if e["cohort_id"] == cohort["id"] and e["status"] == "WAITLISTED"
    ]
    if not waitlisted:
        return None
    nxt = min(waitlisted, key=lambda e: e["waitlist_seq"])
    nxt["status"] = "PENDING_PAYMENT"
    nxt["waitlist_seq"] = None
    db.touch(nxt)
    return nxt


# ---------------------------------------------------------------------------
# Installment-plan refund cascade
# ---------------------------------------------------------------------------

def find_open_plan(enrollment_id):
    for p in db.installment_plans.values():
        if p["enrollment_id"] == enrollment_id and p["status"] == "OPEN":
            return p
    return None


def find_any_plan(enrollment_id):
    """Any installment plan for the enrollment (most recently created wins).

    Used by guarantee refund to read amount_paid_cents when computing the
    conserved refund (PRD §3.7).
    """
    plans = [p for p in db.installment_plans.values() if p["enrollment_id"] == enrollment_id]
    if not plans:
        return None
    return max(plans, key=lambda p: p["_seq"])


def refund_open_plan(enrollment_id):
    """Cascade an OPEN plan OPEN -> REFUNDED (PRD §3.6).

    refund equals amount_paid_cents already collected (conserved). Used by
    enrollment cancellation and guarantee REFUND approval.
    """
    plan = find_open_plan(enrollment_id)
    if plan is None:
        return None
    plan["status"] = "REFUNDED"
    db.touch(plan)
    return plan


# ---------------------------------------------------------------------------
# Enrollment cancellation (shared by direct cancel + all cascades)
# ---------------------------------------------------------------------------

def cancel_enrollment(enrollment):
    """Transition an enrollment to CANCELLED, firing per-state side effects.

    Mirrors the Enrollment -> CANCELLED transitions (scaffold §1.2 / PRD §3.4).
    Caller is responsible for any OCC check and version bump on the cohort.
    The from-state determines the effects:
      ACTIVE          -> release seat, promote waitlist, refund OPEN plan
      PENDING_PAYMENT -> release held seat, promote waitlist
      WAITLISTED      -> clear waitlist_seq; no seat release, no promotion
    """
    prev = enrollment["status"]
    cohort = db.cohorts[enrollment["cohort_id"]]

    enrollment["status"] = "CANCELLED"
    if prev == "WAITLISTED":
        enrollment["waitlist_seq"] = None
        db.touch(enrollment)
        # No seat to release, no promotion.
        return

    db.touch(enrollment)

    if prev == "ACTIVE":
        # Release the committed seat, promote waitlist, refund OPEN plan.
        recompute_seats_committed(cohort)
        promote_waitlist(cohort)
        refund_open_plan(enrollment["id"])
    elif prev == "PENDING_PAYMENT":
        # Release the held seat (held seats are not counted in seats_committed,
        # but recompute keeps the field accurate), then promote waitlist.
        recompute_seats_committed(cohort)
        promote_waitlist(cohort)


# ---------------------------------------------------------------------------
# Score-improvement guarantee eligibility (scaffold §1.3 / PRD §3.7)
# ---------------------------------------------------------------------------

def evaluate_guarantee(enrollment):
    """Set guarantee_status to ELIGIBLE or INELIGIBLE per the four prerequisites
    and the strict guarantee-miss test. Uses best_practice_score (authoritative).
    """
    cohort = db.cohorts[enrollment["cohort_id"]]
    course = db.courses[cohort["course_id"]]
    student = db.students[enrollment["student_id"]]

    if course["format"] == "SELF":
        attendance_ok = True
    else:
        attendance_pct = enrollment["sessions_attended"] / cohort["total_sessions"]
        attendance_ok = attendance_pct >= course["required_attendance_pct"]

    practice_ok = enrollment["completed_practice_count"] >= course["required_practice_tests"]
    have_scores = (
        student["diagnostic_score"] is not None
        and enrollment["best_practice_score"] is not None
    )

    if have_scores:
        improvement = enrollment["best_practice_score"] - student["diagnostic_score"]
        guarantee_missed = improvement < course["guarantee_min_delta"]
    else:
        guarantee_missed = False

    if attendance_ok and practice_ok and have_scores and guarantee_missed:
        new_status = "ELIGIBLE"
    else:
        new_status = "INELIGIBLE"

    if enrollment["guarantee_status"] != new_status:
        enrollment["guarantee_status"] = new_status
        db.touch(enrollment)


# ---------------------------------------------------------------------------
# Materials expiry helper
# ---------------------------------------------------------------------------

def set_materials_expiry(enrollment, course):
    """materials_expire_at = current clock + materials_access_days (PRD §3.4)."""
    expire = db.now_clock() + timedelta(days=course["materials_access_days"])
    enrollment["materials_expire_at"] = db._iso(expire)


def extend_materials_expiry(enrollment, course):
    """Extend materials_expire_at by another materials_access_days window
    (RETAKE grant, PRD §3.7/§3.8). Extends from the existing expiry instant; if
    no expiry was ever set, anchors the new window at the current clock.
    """
    from middleware import parse_iso8601

    if enrollment["materials_expire_at"] is None:
        current = db.now_clock()
    else:
        current = parse_iso8601(enrollment["materials_expire_at"])
    expire = current + timedelta(days=course["materials_access_days"])
    enrollment["materials_expire_at"] = db._iso(expire)
