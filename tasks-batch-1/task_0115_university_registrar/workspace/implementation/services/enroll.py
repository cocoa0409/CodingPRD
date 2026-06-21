"""Enrollment lifecycle: register (enroll/waitlist), drop, withdraw, grade,
section-cancel cascade, and atomic swap.

Validation ordering follows PRD §3.11 exactly.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import db
from errors import err
from services import clock, core
from services.entities import new_common, touch


def _student_active_holds(student_id: str) -> bool:
    return any(
        h["student_id"] == student_id and h["status"] == "ACTIVE"
        for h in db.holds.values()
    )


def _has_non_terminal_enrollment(student_id: str, section_id: str) -> bool:
    for e in db.enrollments.values():
        if e["student_id"] == student_id and e["section_id"] == section_id:
            if e["registration_status"] in ("REQUESTED", "ENROLLED", "WAITLISTED"):
                return True
    return False


# =============================================================================
# POST /enrollments  (PRD §3.4)
# =============================================================================
def register(student_id: str, term: Dict[str, Any], section: Dict[str, Any],
             expected_section_version: int) -> Dict[str, Any]:
    """Evaluate a registration; returns the created Enrollment record.

    Caller has already performed: auth, body validation, existence checks,
    and ownership (X-User-ID == student_id). This function applies the business
    gates in PRD §3.11 order, then routes to ENROLLED or WAITLISTED.
    """
    course = db.courses[section["course_id"]]
    now = clock.now()

    # 6: hold check
    if _student_active_holds(student_id):
        raise err("ERR_REGISTRATION_HOLD", "Student has one or more ACTIVE holds")

    # 7: add-window check
    if term["status"] != "REGISTRATION_OPEN" or now > clock.to_dt(term["add_deadline"]):
        raise err("ERR_ADD_WINDOW_CLOSED", "Term not REGISTRATION_OPEN or past add_deadline")

    # 8: appointment-open check
    appt = core.find_appointment(student_id, term["id"])
    if appt is None or now < clock.to_dt(appt["window_opens_at"]):
        raise err("ERR_APPOINTMENT_NOT_OPEN", "No open appointment for (student, term)")

    # 9: section-open check
    if section["status"] != "OPEN":
        raise err("ERR_SECTION_NOT_OPEN", "Section status is not OPEN")

    # 10: duplicate-enrollment check
    if _has_non_terminal_enrollment(student_id, section["id"]):
        raise err("ERR_DUPLICATE_ENROLLMENT", "Non-terminal enrollment already exists for (student, section)")

    # 11: prerequisites
    if not core.prereqs_satisfied(student_id, course["id"]):
        raise err("ERR_PREREQUISITE_NOT_MET", "A PREREQUISITE course requirement is unsatisfied")

    # 12: corequisites
    if not core.coreqs_satisfied(student_id, term["id"], course["id"]):
        raise err("ERR_COREQUISITE_NOT_MET", "A COREQUISITE course requirement is unsatisfied")

    # 13: time conflict (student schedule, plain overlap, adjacency allowed)
    if core.student_time_conflict(student_id, term["id"], section):
        raise err("ERR_TIME_CONFLICT", "Section overlaps another ENROLLED section on a shared day")

    # 14: credit-limit
    if appt["enrolled_credit_hours"] + course["credit_hours"] > appt["max_credit_hours"]:
        raise err("ERR_CREDIT_LIMIT_EXCEEDED", "Adding the section would exceed max_credit_hours")

    # 15: OCC seat-grab guard
    if expected_section_version != section["version"]:
        raise err("ERR_STALE_VERSION", "expected_section_version does not match the section's version")

    # Seat routing.
    if section["seats_taken"] < section["seat_capacity"]:
        return _do_enroll(student_id, term, section, course)

    # Section full -> waitlist, but only if capacity remains.
    if section["waitlist_count"] >= section["waitlist_capacity"]:
        raise err("ERR_WAITLIST_FULL", "Section is full and its waitlist is at capacity")
    return _do_waitlist(student_id, term, section, course)


def _new_enrollment_base(student_id: str, term: Dict[str, Any], section: Dict[str, Any]) -> Dict[str, Any]:
    rec = new_common("Enrollment")
    rec.update({
        "term_id": term["id"],
        "student_id": student_id,
        "section_id": section["id"],
        "registration_status": "REQUESTED",
        "grade_status": "UNGRADED",
        "letter_grade": None,
        "grade_points": None,
        "tuition_charged_cents": 0,
        "refund_cents": 0,
        "waitlist_position": None,
    })
    return rec


def _do_enroll(student_id, term, section, course) -> Dict[str, Any]:
    rec = _new_enrollment_base(student_id, term, section)
    rec["registration_status"] = "ENROLLED"
    rec["tuition_charged_cents"] = course["credit_hours"] * term["per_credit_cost_cents"]
    db.enrollments[rec["id"]] = rec

    section["seats_taken"] += 1
    touch(section)

    student = db.students[student_id]
    core.recompute_tuition_owed(student)
    core.recompute_enrolled_credit_hours(student_id, term["id"])
    return rec


def _do_waitlist(student_id, term, section, course) -> Dict[str, Any]:
    rec = _new_enrollment_base(student_id, term, section)
    rec["registration_status"] = "WAITLISTED"
    db.enrollments[rec["id"]] = rec

    section["waitlist_count"] += 1
    rec["waitlist_position"] = section["waitlist_count"]
    touch(section)

    core.recompute_enrolled_credit_hours(student_id, term["id"])
    return rec


# =============================================================================
# POST /enrollments/{id}/drop  (PRD §3.5)
# =============================================================================
def drop(enrollment: Dict[str, Any]) -> Dict[str, Any]:
    status = enrollment["registration_status"]
    if status not in ("ENROLLED", "WAITLISTED"):
        raise err("ERR_INVALID_STATE", "Enrollment is not in a droppable state")

    term = db.terms[enrollment["term_id"]]
    section = db.sections[enrollment["section_id"]]
    now = clock.now()

    if status == "ENROLLED":
        # drop window: term REGISTRATION_OPEN|IN_SESSION and now <= drop_deadline
        if term["status"] not in ("REGISTRATION_OPEN", "IN_SESSION") or now > clock.to_dt(term["drop_deadline"]):
            raise err("ERR_DROP_WINDOW_CLOSED", "now past drop_deadline for a drop")
        return _drop_enrolled(enrollment, term, section, triggered_by="DROP")

    # WAITLISTED drop: no window gate, no refund.
    return _drop_waitlisted(enrollment, section)


def _drop_enrolled(enrollment, term, section, triggered_by) -> Dict[str, Any]:
    enrollment["registration_status"] = "DROPPED"
    touch(enrollment)

    section["seats_taken"] -= 1
    touch(section)

    core.credit_refund(enrollment, term, triggered_by)

    student = db.students[enrollment["student_id"]]
    core.recompute_tuition_owed(student)
    core.recompute_enrolled_credit_hours(enrollment["student_id"], term["id"])

    # released seat promotes the head of the waitlist
    core.promote_head_of_waitlist(section)
    return enrollment


def _drop_waitlisted(enrollment, section) -> Dict[str, Any]:
    enrollment["registration_status"] = "DROPPED"
    enrollment["waitlist_position"] = None
    touch(enrollment)

    section["waitlist_count"] -= 1
    touch(section)

    core.renumber_waitlist(section["id"])
    core.recompute_enrolled_credit_hours(enrollment["student_id"], enrollment["term_id"])
    return enrollment


# =============================================================================
# POST /enrollments/{id}/withdraw  (PRD §3.5)
# =============================================================================
def withdraw(enrollment: Dict[str, Any]) -> Dict[str, Any]:
    if enrollment["registration_status"] != "ENROLLED":
        raise err("ERR_INVALID_STATE", "Only an ENROLLED enrollment can be withdrawn")

    term = db.terms[enrollment["term_id"]]
    section = db.sections[enrollment["section_id"]]
    now = clock.now()

    in_window = (
        now > clock.to_dt(term["drop_deadline"])
        and now <= clock.to_dt(term["withdraw_deadline"])
    )
    if not in_window or term["status"] not in ("REGISTRATION_OPEN", "IN_SESSION"):
        raise err("ERR_WITHDRAW_WINDOW_CLOSED", "now not in (drop_deadline, withdraw_deadline] for a withdraw")

    enrollment["registration_status"] = "WITHDRAWN"
    # Records a transcript W mark (PRD §3.5 / §3.8: "the W mark is produced only
    # by a withdrawal"). It carries no grade points and is excluded from GPA;
    # grade_status stays UNGRADED so the W never enters the graded considered set.
    enrollment["letter_grade"] = "W"
    touch(enrollment)

    section["seats_taken"] -= 1
    touch(section)

    core.credit_refund(enrollment, term, "WITHDRAW")

    student = db.students[enrollment["student_id"]]
    core.recompute_tuition_owed(student)
    core.recompute_enrolled_credit_hours(enrollment["student_id"], term["id"])

    core.promote_head_of_waitlist(section)
    return enrollment


# =============================================================================
# POST /enrollments/{id}/grade  (PRD §3.8)
# =============================================================================
def grade(enrollment: Dict[str, Any], letter_grade: str) -> Dict[str, Any]:
    term = db.terms[enrollment["term_id"]]

    # registration_status must be ENROLLED and grade_status UNGRADED.
    if enrollment["registration_status"] != "ENROLLED":
        raise err("ERR_INVALID_STATE", "Only an ENROLLED enrollment may be graded")
    if term["status"] not in ("IN_SESSION", "CLOSED"):
        raise err("ERR_INVALID_STATE", "Grades may be entered only while IN_SESSION or CLOSED")
    if enrollment["grade_status"] == "GRADED":
        raise err("ERR_ALREADY_GRADED", "Enrollment is already GRADED")
    if letter_grade not in core.GRADE_POINTS:
        raise err("ERR_INVALID_GRADE", "Grade letter must be one of A,B,C,D,F")

    enrollment["grade_status"] = "GRADED"
    enrollment["letter_grade"] = letter_grade
    enrollment["grade_points"] = core.GRADE_POINTS[letter_grade]
    touch(enrollment)

    student = db.students[enrollment["student_id"]]
    core.recompute_gpa_and_standing(student)
    return enrollment


# =============================================================================
# Section cancellation cascade  (PRD §3.6)
# =============================================================================
def cancel_section_cascade(section: Dict[str, Any]) -> None:
    """Unwind every enrollment on a section being CANCELLED."""
    term = db.terms[section["term_id"]]

    on_section = [
        e for e in db.enrollments.values()
        if e["section_id"] == section["id"]
        and e["registration_status"] in ("ENROLLED", "WAITLISTED")
    ]
    # Process ENROLLED then WAITLISTED; deterministic order by created_at.
    on_section.sort(key=lambda e: (e["created_at"], e["_seq"]))

    for e in on_section:
        if e["registration_status"] == "ENROLLED":
            e["registration_status"] = "DROPPED"
            touch(e)
            section["seats_taken"] -= 1
            touch(section)
            core.credit_refund(e, term, "SECTION_CANCEL")
            student = db.students[e["student_id"]]
            core.recompute_tuition_owed(student)
            core.recompute_enrolled_credit_hours(e["student_id"], term["id"])
        elif e["registration_status"] == "WAITLISTED":
            e["registration_status"] = "DROPPED"
            e["waitlist_position"] = None
            touch(e)
            section["waitlist_count"] -= 1
            touch(section)
            core.recompute_enrolled_credit_hours(e["student_id"], term["id"])
    # No waitlist promotion: the section itself is terminating.


# =============================================================================
# POST /swap-requests  (PRD §3.10)
# =============================================================================
def evaluate_swap(student_id: str, term: Dict[str, Any], drop_enrollment: Dict[str, Any],
                  add_section: Dict[str, Any], expected_section_version: int) -> Dict[str, Any]:
    """Atomic add-then-drop. Returns the SwapRequest record (COMMITTED/ABORTED).

    Caller has performed auth, body validation, existence, and ownership of the
    swap (X-User-ID == student_id). The add-leg precondition failures are
    raised as APIError; the caller wraps to record ABORTED and re-raise.
    """
    course = db.courses[add_section["course_id"]]
    now = clock.now()

    # hold check
    if _student_active_holds(student_id):
        raise err("ERR_REGISTRATION_HOLD", "Student has one or more ACTIVE holds")

    # add-window check
    if term["status"] != "REGISTRATION_OPEN" or now > clock.to_dt(term["add_deadline"]):
        raise err("ERR_ADD_WINDOW_CLOSED", "Term not REGISTRATION_OPEN or past add_deadline")

    # appointment-open check
    appt = core.find_appointment(student_id, term["id"])
    if appt is None or now < clock.to_dt(appt["window_opens_at"]):
        raise err("ERR_APPOINTMENT_NOT_OPEN", "No open appointment for (student, term)")

    # drop_enrollment must be ENROLLED, owned by the student, in this term.
    if (
        drop_enrollment["student_id"] != student_id
        or drop_enrollment["term_id"] != term["id"]
        or drop_enrollment["registration_status"] != "ENROLLED"
    ):
        raise err("ERR_INVALID_STATE", "drop_enrollment is not an ENROLLED enrollment owned by the student in this term")

    # add_section must be OPEN with a free seat.
    if add_section["status"] != "OPEN" or add_section["seats_taken"] >= add_section["seat_capacity"]:
        raise err("ERR_SECTION_FULL", "Add section is not OPEN or has no free seats")

    # prerequisites / corequisites
    if not core.prereqs_satisfied(student_id, course["id"]):
        raise err("ERR_PREREQUISITE_NOT_MET", "A PREREQUISITE course requirement is unsatisfied")
    if not core.coreqs_satisfied(student_id, term["id"], course["id"]):
        raise err("ERR_COREQUISITE_NOT_MET", "A COREQUISITE course requirement is unsatisfied")

    # credit-limit check
    if appt["enrolled_credit_hours"] + course["credit_hours"] > appt["max_credit_hours"]:
        raise err("ERR_CREDIT_LIMIT_EXCEEDED", "Adding the section would exceed max_credit_hours")

    # time conflict, evaluated as if the drop has been applied (exclude the
    # dropped enrollment's section from the student's ENROLLED schedule).
    if core.student_time_conflict(student_id, term["id"], add_section,
                                  exclude_enrollment_id=drop_enrollment["id"]):
        raise err("ERR_TIME_CONFLICT", "Add section overlaps another ENROLLED section on a shared day")

    # OCC seat-grab guard on the add section.
    if expected_section_version != add_section["version"]:
        raise err("ERR_STALE_VERSION", "expected_section_version does not match the add section's version")

    # ---- COMMIT: create the added enrollment ENROLLED on add_section --------
    added = _do_enroll(student_id, term, add_section, course)

    # ---- then drive drop_enrollment -> DROPPED -----------------------------
    old_section = db.sections[drop_enrollment["section_id"]]
    _drop_enrolled(drop_enrollment, term, old_section, triggered_by="DROP")

    return added
