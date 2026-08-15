"""State-machine side-effect bundles (scaffold `state_machines`).

The nine state machines:
  HighSchool            ACTIVE -> SUSPENDED
  AcademicTerm          SCHEDULED -> OPEN -> CLOSED (close cascades WAITLISTED -> EXPIRED)
  Student               ELIGIBLE -> SUSPENDED
  Course                ACTIVE -> RETIRED
  CredentialApplication SUBMITTED -> UNDER_REVIEW -> APPROVED/DENIED/NEEDS_REVISION -> SUBMITTED
  CourseOffering        DRAFT -> OPEN -> IN_SESSION -> GRADING -> FINALIZED; DRAFT/OPEN -> CANCELLED
  Enrollment            PENDING_VERIFICATION -> REGISTERED/WAITLISTED/CANCELLED;
                        REGISTERED -> DROPPED/WITHDRAWN/COMPLETED; WITHDRAWN -> REGISTERED; ...
  Invoice               ISSUED -> PARTIALLY_PAID -> PAID; any -> VOIDED; refund_status axis
  TranscriptEntry       PENDING -> POSTED -> VOIDED

The single-resource transitions live inline in their route modules; this module
holds the multi-entity cascades and posting rules.
"""
from db import db
from services.calculations import (
    apply_refund_estimate,
    current_invoice,
    entry_grade_points,
    promote_waitlist,
    DROP_REFUND_PCT,
)
from services.core import new_record, touch


def release_seat_and_promote(offering):
    """Drop / withdraw side effect: the released seat bumps the offering
    version, then waitlist_promotion may fire (bumping it again)."""
    touch(offering)  # seat released: CourseOffering.version += 1
    promote_waitlist(offering)


def settle_enrollment_invoice(enrollment, pct):
    """Drop / withdraw / admin-drop invoice settlement per refund_settlement's
    estimate variant, against the enrollment's current (latest) invoice."""
    invoice = current_invoice(enrollment["id"])
    if invoice is not None:
        apply_refund_estimate(invoice, pct)
    return invoice


def close_registration_cascade(term):
    """AcademicTerm OPEN -> CLOSED: every WAITLISTED enrollment whose offering
    is tied to this term (college_term_id OR hs_term_id) becomes EXPIRED.
    waitlist_seq is retained, never reused. PENDING_VERIFICATION is untouched."""
    for enrollment in db["enrollments"].values():
        if enrollment["status"] != "WAITLISTED":
            continue
        offering = db["offerings"].get(enrollment["offering_id"])
        if offering is None:
            continue
        if offering["college_term_id"] == term["id"] or offering["hs_term_id"] == term["id"]:
            enrollment["status"] = "EXPIRED"
            touch(enrollment)  # Enrollment.version += 1


def cancel_offering_cascade(offering):
    """CourseOffering DRAFT|OPEN -> CANCELLED conditional cascade:
    PENDING_VERIFICATION -> CANCELLED; WAITLISTED -> CANCELLED;
    REGISTERED -> DROPPED (administrative drop) with its Invoice voided at
    refund_pct 100. Terminal enrollments are untouched."""
    for enrollment in db["enrollments"].values():
        if enrollment["offering_id"] != offering["id"]:
            continue
        if enrollment["status"] in ("PENDING_VERIFICATION", "WAITLISTED"):
            enrollment["status"] = "CANCELLED"
            touch(enrollment)
        elif enrollment["status"] == "REGISTERED":
            enrollment["status"] = "DROPPED"
            touch(enrollment)
            settle_enrollment_invoice(enrollment, DROP_REFUND_PCT)


def finalize_offering_posting(offering):
    """CourseOffering GRADING -> FINALIZED transcript posting rules.

    COMPLETED (REGISTERED + graded): one COLLEGE entry (college_credit_hours)
    and one HIGH_SCHOOL entry (hs_credit_units), both PENDING, grade copied.
    WITHDRAWN: COLLEGE PENDING entry with grade W always; HIGH_SCHOOL PENDING
    entry with grade W only when withdrawn_at > hs_term.drop_deadline.
    DROPPED / CANCELLED / EXPIRED: no entries."""
    course = db["courses"][offering["course_id"]]
    hs_term = db["terms"][offering["hs_term_id"]]

    enrollments = [
        e for e in db["enrollments"].values() if e["offering_id"] == offering["id"]
    ]
    enrollments.sort(key=lambda e: (e["created_at"], e["_seq"]))

    for enrollment in enrollments:
        if enrollment["status"] == "REGISTERED":
            enrollment["status"] = "COMPLETED"
            touch(enrollment)
            _create_transcript_entry(
                enrollment, "COLLEGE", enrollment["grade"], course["college_credit_hours"]
            )
            _create_transcript_entry(
                enrollment, "HIGH_SCHOOL", enrollment["grade"], course["hs_credit_units"]
            )
        elif enrollment["status"] == "WITHDRAWN":
            _create_transcript_entry(
                enrollment, "COLLEGE", "W", course["college_credit_hours"]
            )
            withdrawn_at = enrollment.get("_withdrawn_at")
            if withdrawn_at is not None and withdrawn_at > hs_term["_drop_deadline"]:
                _create_transcript_entry(
                    enrollment, "HIGH_SCHOOL", "W", course["hs_credit_units"]
                )


def _create_transcript_entry(enrollment, institution, grade, credit_value):
    return new_record(
        "transcript_entries",
        {
            "enrollment_id": enrollment["id"],
            "institution": institution,
            "grade": grade,
            "credit_value": credit_value,
            "grade_points": entry_grade_points(institution, grade, credit_value),
            "status": "PENDING",
        },
    )
