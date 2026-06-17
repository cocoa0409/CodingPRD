"""Enrollment progress, weighted scoring, completion, and lazy expiry.

Calculations (scaffold §1.3):
 - lesson_completion_score
 - course_weighted_score (weighted_gate variant — authoritative)
 - completion gate (ACTIVE -> COMPLETED)
 - lazy ACTIVE -> EXPIRED on read/write past refund_deadline
"""
import clock
from db import db, new_id, iso
from services.common import (round_4dp, round_2dp, touch, stamp_create, parse_dt)
from services.course_derived import recompute_enrollment_count


# --------------------------------------------------------------------------
# Lesson completion scoring (calc lesson_completion_score)
# --------------------------------------------------------------------------

def score_completion(lesson, course, correct_answers):
    """Return (score_pct, passed) for a completion against its lesson."""
    if lesson.get("is_graded"):
        qc = lesson.get("question_count", 0)
        # qc >= 1 guaranteed for graded lessons at create time.
        score_pct = round_4dp(correct_answers / qc)
        passed = score_pct >= course["passing_score_pct"]  # inclusive >=
        return score_pct, passed
    else:
        return 1.0, True


# --------------------------------------------------------------------------
# Weighted score (calc course_weighted_score, weighted_gate variant)
# --------------------------------------------------------------------------

def graded_published_lessons(course_id):
    return [l for l in db.lessons.values()
            if l["course_id"] == course_id and l.get("is_graded")
            and l.get("is_published")]


def compute_weighted_score(enrollment, course):
    """numerator = sum(lc.score_pct * L.quiz_weight) over graded published
    lessons that HAVE a completion on this enrollment;
    denominator = total quiz_weight across ALL graded published lessons (fixed).
    Returns weighted_score_pct rounded to 4dp. If no graded lessons, returns 0.0
    (the course auto-satisfies the score gate elsewhere)."""
    graded = graded_published_lessons(course["id"])
    total_weight = sum(l.get("quiz_weight", 0) for l in graded)
    if total_weight <= 0:
        return 0.0
    # completions for this enrollment keyed by lesson_id
    comps = {c["lesson_id"]: c for c in db.lesson_completions.values()
             if c["enrollment_id"] == enrollment["id"]}
    numerator = 0.0
    for l in graded:
        c = comps.get(l["id"])
        if c is not None:
            numerator += c["score_pct"] * l.get("quiz_weight", 0)
    return round_4dp(numerator / total_weight)


def recompute_progress(enrollment, course):
    """Recompute completed_lesson_count, progress_pct, weighted_score_pct in
    place (does not touch — caller decides). passed completions only count."""
    eid = enrollment["id"]
    comps = [c for c in db.lesson_completions.values()
             if c["enrollment_id"] == eid]
    completed = sum(1 for c in comps if c.get("passed"))
    enrollment["completed_lesson_count"] = completed
    plc = course.get("published_lesson_count", 0)
    if plc > 0:
        enrollment["progress_pct"] = round_2dp(completed / plc)
    else:
        enrollment["progress_pct"] = 0.0
    enrollment["weighted_score_pct"] = compute_weighted_score(enrollment, course)


# --------------------------------------------------------------------------
# Completion gate (ACTIVE -> COMPLETED)
# --------------------------------------------------------------------------

def try_complete(enrollment, course):
    """If the enrollment qualifies, transition ACTIVE -> COMPLETED, award CEU,
    and issue exactly one Certificate. Returns True if it completed.

    A COMPLETED enrollment never moves money (SALE ledger untouched)."""
    if enrollment["status"] != "ACTIVE":
        return False
    has_graded = len(graded_published_lessons(course["id"])) > 0
    progress_ok = enrollment["progress_pct"] >= course["completion_threshold_pct"]
    if has_graded:
        score_ok = enrollment["weighted_score_pct"] >= course["passing_score_pct"]
    else:
        score_ok = True  # course with no graded lessons auto-satisfies
    if not (progress_ok and score_ok):
        return False

    enrollment["status"] = "COMPLETED"
    enrollment["ceu_awarded"] = course["ceu_credits"]
    issue_certificate(enrollment, course)
    touch(enrollment)
    return True


def issue_certificate(enrollment, course):
    """Issue exactly one immutable Certificate (id + created_at only)."""
    now = clock.now()
    rec = {
        "id": new_id(),
        "enrollment_id": enrollment["id"],
        "course_id": enrollment["course_id"],
        "learner_id": enrollment["learner_id"],
        "ceu_credits": course["ceu_credits"],
        "final_score_pct": round_4dp(enrollment["weighted_score_pct"]),
        "issued_at": iso(now),
        "created_at": iso(now),
    }
    rec["_seq"] = db.next_seq()
    db.certificates[rec["id"]] = rec
    return rec


# --------------------------------------------------------------------------
# Lazy expiry (ACTIVE -> EXPIRED) and refund-deadline helpers
# --------------------------------------------------------------------------

def refund_deadline_dt(enrollment):
    return parse_dt(enrollment["refund_deadline"])


def maybe_expire(enrollment):
    """Lazily transition an ACTIVE enrollment to EXPIRED when the clock has
    reached/passed refund_deadline. Side effect: flip the SALE ledger entry
    PENDING -> AVAILABLE and recompute the instructor's balances.

    Touches the enrollment iff it transitions. Safe to call on any read/write.
    """
    if enrollment["status"] != "ACTIVE":
        return False
    deadline = refund_deadline_dt(enrollment)
    if clock.now() < deadline:
        return False
    # transition
    enrollment["status"] = "EXPIRED"
    # flip the SALE ledger entry to AVAILABLE
    from services.ledger import recompute_balances
    sale = _sale_entry_for(enrollment["id"])
    if sale is not None and sale["status"] == "PENDING":
        sale["status"] = "AVAILABLE"
        recompute_balances(_instructor_of_enrollment(enrollment))
    touch(enrollment)
    return True


def _sale_entry_for(enrollment_id):
    for e in db.ledger_entries.values():
        if e["enrollment_id"] == enrollment_id and e["entry_type"] == "SALE":
            return e
    return None


def _instructor_of_enrollment(enrollment):
    course = db.courses.get(enrollment["course_id"])
    return course["instructor_id"] if course else None
