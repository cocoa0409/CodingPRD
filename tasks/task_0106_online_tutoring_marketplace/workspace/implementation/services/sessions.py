"""Session lifecycle helpers — cancellation, completion, refund cascades."""

from clock import clock, parse_iso
from db import db, touch
from services.pricing import (
    compute_actual_gross_cents,
    compute_cancellation_fee_cents,
    compute_commission_cents,
    scheduled_minutes_of,
)


def _session_scheduled_minutes(session):
    return scheduled_minutes_of(parse_iso(session["start_at"]), parse_iso(session["end_at"]))


def cancel_session_by_student(session, by_tutor_or_system=False):
    """Manual student/parent cancel. Computes hours-to-start and applies fee ladder."""
    now = clock.now()
    start_at = parse_iso(session["start_at"])
    hours = (start_at - now).total_seconds() / 3600.0
    fee = compute_cancellation_fee_cents(
        session["charged_amount_cents"], hours, by_tutor_or_system=by_tutor_or_system
    )
    refund = session["charged_amount_cents"] - fee
    session["cancellation_fee_cents"] = fee
    session["refund_to_student_cents"] = refund
    session["status"] = "CANCELLED_BY_STUDENT"
    # Credit the student
    student = db.students.get(session["student_id"])
    if student is not None and refund > 0:
        student["credit_balance_cents"] = student.get("credit_balance_cents", 0) + refund
        touch(student)
    touch(session)


def cancel_session_by_tutor(session):
    """Manual tutor cancel — fee 0, full refund."""
    refund = session["charged_amount_cents"]
    session["cancellation_fee_cents"] = 0
    session["refund_to_student_cents"] = refund
    session["status"] = "CANCELLED_BY_TUTOR"
    student = db.students.get(session["student_id"])
    if student is not None and refund > 0:
        student["credit_balance_cents"] = student.get("credit_balance_cents", 0) + refund
        touch(student)
    touch(session)


def force_cancel_session_by_tutor_cascade(session):
    """Cascade from Tutor SUSPENDED / Credential EXPIRED. Fee 0, full refund."""
    cancel_session_by_tutor(session)


def cascade_cancel_for_child_link_revoke(student_id):
    """Cascade from ParentChildLink REVOKE. Cancel future REQUESTED/CONFIRMED sessions
    as CANCELLED_BY_STUDENT with cancellation fee per the standard fee ladder."""
    now = clock.now()
    affected = []
    for s in list(db.sessions.values()):
        if s["student_id"] != student_id:
            continue
        if s["status"] not in ("REQUESTED", "CONFIRMED"):
            continue
        start_at = parse_iso(s["start_at"])
        if start_at > now:
            affected.append(s)
    affected.sort(key=lambda r: r["id"])
    for s in affected:
        cancel_session_by_student(s, by_tutor_or_system=False)


def complete_session(session, adjusted_minutes_arg):
    """Transition IN_PROGRESS -> COMPLETED. Pin actuals, commission, payout."""
    tutor = db.tutors[session["tutor_id"]]
    scheduled = _session_scheduled_minutes(session)
    actual = adjusted_minutes_arg if adjusted_minutes_arg is not None else scheduled
    # Recompute actual gross
    actual_gross = compute_actual_gross_cents(
        tutor, scheduled, actual, session["is_trial"]
    )
    session["actual_gross_cents"] = actual_gross
    session["adjusted_minutes"] = actual

    short_delivery = max(session["gross_price_cents"] - actual_gross, 0)
    if short_delivery > 0:
        session["refund_to_student_cents"] = session.get("refund_to_student_cents", 0) + short_delivery
        student = db.students.get(session["student_id"])
        if student is not None:
            student["credit_balance_cents"] = student.get("credit_balance_cents", 0) + short_delivery
            touch(student)

    # Increment lifetime BEFORE computing commission so tier is "at moment of completion"
    tutor["lifetime_completed_sessions"] = tutor.get("lifetime_completed_sessions", 0) + 1
    touch(tutor)

    commission = compute_commission_cents(actual_gross, tutor["lifetime_completed_sessions"])
    session["final_commission_cents"] = commission
    session["tutor_payout_cents"] = max(actual_gross - commission, 0)
    session["status"] = "COMPLETED"
    touch(session)


def settle_session(session):
    """COMPLETED -> SETTLED (via clock sweep). Credit tutor.payout_balance_cents."""
    tutor = db.tutors.get(session["tutor_id"])
    if tutor is not None:
        tutor["payout_balance_cents"] = tutor.get("payout_balance_cents", 0) + session.get("tutor_payout_cents", 0)
        touch(tutor)
    session["status"] = "SETTLED"
    touch(session)


def refund_session_from_dispute(session, dispute):
    """DISPUTED -> REFUNDED cascade from RESOLVED_REFUND."""
    tutor = db.tutors[session["tutor_id"]]
    arbitration_refund = dispute.get("resolved_refund_cents", 0) or 0
    session["arbitration_refund_cents"] = arbitration_refund
    session["refund_to_student_cents"] = session.get("refund_to_student_cents", 0) + arbitration_refund
    student = db.students.get(session["student_id"])
    if student is not None and arbitration_refund > 0:
        student["credit_balance_cents"] = student.get("credit_balance_cents", 0) + arbitration_refund
        touch(student)
    # Recompute commission FINAL_AFTER_REFUND
    service_revenue_retained = max(session.get("actual_gross_cents", 0) - arbitration_refund, 0)
    commission = compute_commission_cents(
        service_revenue_retained, tutor.get("lifetime_completed_sessions", 0)
    )
    session["final_commission_cents"] = commission
    session["tutor_payout_cents"] = max(service_revenue_retained - commission, 0)
    session["status"] = "REFUNDED"
    touch(session)


def settle_session_from_dispute_deny(session):
    """DISPUTED -> SETTLED cascade from RESOLVED_DENY."""
    tutor = db.tutors.get(session["tutor_id"])
    if tutor is not None:
        tutor["payout_balance_cents"] = tutor.get("payout_balance_cents", 0) + session.get("tutor_payout_cents", 0)
        touch(tutor)
    session["status"] = "SETTLED"
    touch(session)


def sessions_overlap(s1, s2):
    """Closed-open intervals [start_at, end_at) with 0-min buffer."""
    a_start = parse_iso(s1["start_at"])
    a_end = parse_iso(s1["end_at"])
    b_start = parse_iso(s2["start_at"])
    b_end = parse_iso(s2["end_at"])
    return a_start < b_end and b_start < a_end
