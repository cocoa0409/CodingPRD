"""Core business logic: calculations, derived-field reconciliation,
enrollment lifecycle, waitlist promotion, cascades, and swap.

All behavior here traces to PRD §2-§3.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

import db
from errors import err
from services import clock
from services.entities import new_common, touch

# ---- grade point map (PRD §3.8) ---------------------------------------------
GRADE_POINTS = {"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0, "F": 0.0}
PASSING_GRADE_LETTERS = {"A", "B", "C", "D"}  # D or better => grade_points >= 1.0


# ---- rounding helper --------------------------------------------------------
def round_half_up_cents(value: Decimal) -> int:
    """Round a Decimal cent value half-up to a whole integer cent (PRD §2.7)."""
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value: Decimal) -> float:
    """Round a Decimal to 2 decimals half-up; return as float (PRD §2.7)."""
    q = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


# ---- meeting-day overlap helpers (PRD §3.2 / §3.4) --------------------------
def share_day(days_a: str, days_b: str) -> bool:
    """True iff the two day-codes share at least one day letter."""
    return bool(set(days_a) & set(days_b))


# =============================================================================
# Derived-field reconciliation
# =============================================================================
def student_enrollments(student_id: str) -> List[Dict[str, Any]]:
    return [e for e in db.enrollments.values() if e["student_id"] == student_id]


def recompute_tuition_owed(student: Dict[str, Any]) -> None:
    """tuition_owed_cents (PRD §3.9 / calc tuition_owed).

    charged  = sum frozen tuition_charged_cents over enrollments in
               {ENROLLED, WITHDRAWN, DROPPED}
    refunded = sum amount_cents over the student's RefundTransactions
    owed = charged - refunded
    """
    charged = sum(
        e["tuition_charged_cents"]
        for e in student_enrollments(student["id"])
        if e["registration_status"] in ("ENROLLED", "WITHDRAWN", "DROPPED")
    )
    refunded = sum(
        rt["amount_cents"]
        for rt in db.refund_transactions.values()
        if rt["student_id"] == student["id"]
    )
    new_val = charged - refunded
    if student["tuition_owed_cents"] != new_val:
        student["tuition_owed_cents"] = new_val
        touch(student)
    else:
        # Even when the numeric value is unchanged, a recomputation is a
        # mutation per PRD §2.4 only if the field actually changed. We bump
        # only on real change to avoid spurious version drift.
        pass


def recompute_gpa_and_standing(student: Dict[str, Any]) -> None:
    """Cumulative GPA, earned_credit_hours, academic_standing (PRD §3.8)."""
    considered = [
        e for e in student_enrollments(student["id"])
        if e["grade_status"] == "GRADED" and e["letter_grade"] in GRADE_POINTS
    ]
    total_quality = Decimal(0)
    total_credits = 0
    for e in considered:
        course = db.courses[db.sections[e["section_id"]]["course_id"]]
        ch = course["credit_hours"]
        total_quality += Decimal(str(GRADE_POINTS[e["letter_grade"]])) * Decimal(ch)
        total_credits += ch

    if total_credits == 0:
        gpa = 0.00
    else:
        gpa = round_half_up_2dp(total_quality / Decimal(total_credits))

    # earned_credit_hours = completed + credits of passing-grade enrollments.
    earned = student["completed_credit_hours"]
    for e in considered:
        if e["letter_grade"] in PASSING_GRADE_LETTERS:
            course = db.courses[db.sections[e["section_id"]]["course_id"]]
            earned += course["credit_hours"]

    # academic_standing from GPA. Zero graded credits => GOOD.
    if total_credits == 0:
        standing = "GOOD"
    elif gpa >= 2.00:
        standing = "GOOD"
    elif gpa >= 1.00:
        standing = "WARNING"
    else:
        standing = "PROBATION"

    changed = (
        student["gpa"] != gpa
        or student["earned_credit_hours"] != earned
        or student["academic_standing"] != standing
    )
    if changed:
        student["gpa"] = gpa
        student["earned_credit_hours"] = earned
        student["academic_standing"] = standing
        touch(student)


def find_appointment(student_id: str, term_id: str) -> Optional[Dict[str, Any]]:
    for a in db.appointments.values():
        if a["student_id"] == student_id and a["term_id"] == term_id:
            return a
    return None


def recompute_enrolled_credit_hours(student_id: str, term_id: str) -> None:
    """appointment.enrolled_credit_hours (PRD §3.3 / calc enrolled_credit_hours).

    Sum of Course.credit_hours over the student's ENROLLED+WAITLISTED
    enrollments in the term.
    """
    appt = find_appointment(student_id, term_id)
    if appt is None:
        return
    total = 0
    for e in db.enrollments.values():
        if (
            e["student_id"] == student_id
            and e["term_id"] == term_id
            and e["registration_status"] in ("ENROLLED", "WAITLISTED")
        ):
            course = db.courses[db.sections[e["section_id"]]["course_id"]]
            total += course["credit_hours"]
    if appt["enrolled_credit_hours"] != total:
        appt["enrolled_credit_hours"] = total
        touch(appt)


def renumber_waitlist(section_id: str) -> None:
    """Reassign 1-based waitlist_position over a section's WAITLISTED enrollments
    ordered by created_at ASC (tie-break by insertion sequence)."""
    wl = [
        e for e in db.enrollments.values()
        if e["section_id"] == section_id and e["registration_status"] == "WAITLISTED"
    ]
    wl.sort(key=lambda e: (e["created_at"], e["_seq"]))
    for idx, e in enumerate(wl, start=1):
        if e["waitlist_position"] != idx:
            e["waitlist_position"] = idx
            touch(e)


# =============================================================================
# Prerequisite / corequisite satisfaction (PRD §3.4 / calc prerequisite)
# =============================================================================
def prereqs_satisfied(student_id: str, course_id: str) -> bool:
    """Every PREREQUISITE edge of the course satisfied by prior graded history."""
    for req in db.course_requirements.values():
        if req["course_id"] != course_id or req["requirement_type"] != "PREREQUISITE":
            continue
        if not _prereq_edge_ok(student_id, req):
            return False
    return True


def _prereq_edge_ok(student_id: str, req: Dict[str, Any]) -> bool:
    required_course_id = req["required_course_id"]
    min_pts = req["min_grade_points"]
    for g in student_enrollments(student_id):
        if g["grade_status"] != "GRADED":
            continue
        if g["letter_grade"] == "W" or g["letter_grade"] is None:
            continue
        g_course_id = db.sections[g["section_id"]]["course_id"]
        if g_course_id != required_course_id:
            continue
        gp = g["grade_points"]
        if gp is not None and gp >= min_pts:
            return True
    return False


def coreqs_satisfied(student_id: str, term_id: str, course_id: str) -> bool:
    """Every COREQUISITE edge satisfied by a same-term enrollment of the
    required course in {ENROLLED, WAITLISTED, REQUESTED}."""
    for req in db.course_requirements.values():
        if req["course_id"] != course_id or req["requirement_type"] != "COREQUISITE":
            continue
        if not _coreq_edge_ok(student_id, term_id, req):
            return False
    return True


def _coreq_edge_ok(student_id: str, term_id: str, req: Dict[str, Any]) -> bool:
    required_course_id = req["required_course_id"]
    for c in db.enrollments.values():
        if c["student_id"] != student_id or c["term_id"] != term_id:
            continue
        if c["registration_status"] not in ("ENROLLED", "WAITLISTED", "REQUESTED"):
            continue
        if db.sections[c["section_id"]]["course_id"] == required_course_id:
            return True
    return False


# =============================================================================
# Student schedule time conflict (PRD §3.4) — plain half-open overlap, no buffer
# =============================================================================
def student_time_conflict(
    student_id: str, term_id: str, new_section: Dict[str, Any],
    exclude_enrollment_id: Optional[str] = None,
) -> bool:
    """True iff new_section overlaps any of the student's other ENROLLED sections
    on a shared day (half-open overlap, adjacency allowed, no buffer)."""
    for e in db.enrollments.values():
        if e["student_id"] != student_id or e["term_id"] != term_id:
            continue
        if e["registration_status"] != "ENROLLED":
            continue
        if exclude_enrollment_id is not None and e["id"] == exclude_enrollment_id:
            continue
        other = db.sections[e["section_id"]]
        if other["id"] == new_section["id"]:
            continue
        if not share_day(new_section["meeting_days"], other["meeting_days"]):
            continue
        if (
            new_section["meeting_start_min"] < other["meeting_end_min"]
            and other["meeting_start_min"] < new_section["meeting_end_min"]
        ):
            return True
    return False


# =============================================================================
# Refund calculation (PRD §3.7 / calc enrollment_refund)
# =============================================================================
def compute_refund(enrollment: Dict[str, Any], term: Dict[str, Any], triggered_by: str):
    """Return (refund_tier, amount_cents) for a drop/withdraw/section-cancel."""
    base = enrollment["tuition_charged_cents"]
    now = clock.now()

    if triggered_by == "SECTION_CANCEL":
        tier = "FULL"
        pct = term["refund_full_pct"]
    elif now <= clock.to_dt(term["drop_deadline"]):
        tier = "FULL"
        pct = term["refund_full_pct"]
    elif now <= clock.to_dt(term["withdraw_deadline"]):
        tier = "PARTIAL"
        pct = term["refund_partial_pct"]
    else:
        tier = "NONE"
        pct = 0.0

    amount = round_half_up_cents(Decimal(base) * Decimal(str(pct)))
    return tier, amount


def credit_refund(enrollment: Dict[str, Any], term: Dict[str, Any], triggered_by: str) -> Dict[str, Any]:
    """Create a RefundTransaction and set enrollment.refund_cents."""
    tier, amount = compute_refund(enrollment, term, triggered_by)
    rt = new_common("RefundTransaction")
    rt.update({
        "enrollment_id": enrollment["id"],
        "student_id": enrollment["student_id"],
        "refund_tier": tier,
        "amount_cents": amount,
        "triggered_by": triggered_by,
    })
    db.refund_transactions[rt["id"]] = rt
    enrollment["refund_cents"] = amount
    return rt


# =============================================================================
# Waitlist promotion (PRD §3.5)
# =============================================================================
def promote_head_of_waitlist(section: Dict[str, Any]) -> None:
    """If a seat is available, promote the head WAITLISTED enrollment of the
    section to ENROLLED, with all side effects."""
    if section["seats_taken"] >= section["seat_capacity"]:
        return
    wl = [
        e for e in db.enrollments.values()
        if e["section_id"] == section["id"] and e["registration_status"] == "WAITLISTED"
    ]
    if not wl:
        return
    wl.sort(key=lambda e: (e["waitlist_position"], e["created_at"], e["_seq"]))
    head = wl[0]

    term = db.terms[section["term_id"]]
    course = db.courses[section["course_id"]]

    head["registration_status"] = "ENROLLED"
    head["waitlist_position"] = None
    head["tuition_charged_cents"] = course["credit_hours"] * term["per_credit_cost_cents"]
    touch(head)

    section["seats_taken"] += 1
    section["waitlist_count"] -= 1
    touch(section)

    renumber_waitlist(section["id"])

    promoted_student = db.students[head["student_id"]]
    recompute_tuition_owed(promoted_student)
    recompute_enrolled_credit_hours(head["student_id"], head["term_id"])
