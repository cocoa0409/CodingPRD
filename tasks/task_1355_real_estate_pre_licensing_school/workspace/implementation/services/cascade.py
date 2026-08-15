"""Cascade helpers for state transitions with side effects."""

import db
from services.calculations import (
    compute_refund_scheduled, compute_refund_statutory, compute_granted_refund,
    update_offering_counts, _extract_date, build_amendment_lines,
)


def cancel_offering_cascade(offering, auth_role, auth_id, from_status=None):
    """Cascade: cancel an offering -> withdraw enrollments, create refunds."""
    today = db.today()
    now_iso = db.now_iso()

    # L1: Withdraw active enrollments
    for enrollment in list(db.enrollments.values()):
        if enrollment["offering_id"] != offering["id"]:
            continue
        if enrollment["academic_status"] not in ("ENROLLED", "IN_PROGRESS", "SEAT_TIME_MET", "EXAM_PASSED"):
            continue

        old_status = enrollment["academic_status"]
        enrollment["academic_status"] = "WITHDRAWN"
        enrollment["withdrawal_reason"] = "SCHOOL_CANCELLED"
        enrollment["withdrawn_at"] = now_iso
        db.touch(enrollment)
        db.audit("Enrollment", enrollment["id"], "STATUS_CHANGE",
                 "system", "system",
                 {"from_status": old_status, "to_status": "WITHDRAWN"})

        # L2: Refund handling
        if enrollment["payment_status"] == "PAID":
            # Auto-create RefundRequest with full refund
            paid = enrollment["paid_cents"]
            refund_req = db.new_entity({
                "enrollment_id": enrollment["id"],
                "reason": "SCHOOL_CANCELLED",
                "status": "PENDING",
                "completion_fraction_bps_at_withdrawal": enrollment.get("completion_fraction_bps", 0),
                "scheduled_refund_cents": paid,
                "statutory_refund_cents": paid,
                "granted_refund_cents": paid,
                "denial_reason": None,
                "decided_at": None,
                "paid_at": None,
            })
            db.refund_requests[refund_req["id"]] = refund_req
            db.audit("RefundRequest", refund_req["id"], "REFUND_REQUEST_CREATED",
                     "system", "system", {})
        elif enrollment["payment_status"] == "PENDING":
            enrollment["payment_status"] = "VOIDED"
            db.touch(enrollment)

    # L3: Recompute offering counts
    update_offering_counts(offering)
    db.touch(offering)
    db.audit("CourseOffering", offering["id"], "CASCADED_CANCELLATION",
             "system", "system",
             {"from_status": from_status, "to_status": "CANCELLED"})


def withdraw_enrollment(enrollment, reason, effective_date_str, auth_role, auth_id):
    """Withdraw an enrollment with side effects W1-W3."""
    from datetime import date as date_cls

    old_status = enrollment["academic_status"]

    # W1: Set withdrawal fields
    if effective_date_str:
        enrollment["withdrawn_at"] = effective_date_str
        withdrawal_date = _extract_date(effective_date_str)
    else:
        enrollment["withdrawn_at"] = db.now_iso()
        withdrawal_date = db.today()

    enrollment["academic_status"] = "WITHDRAWN"
    enrollment["withdrawal_reason"] = reason
    db.touch(enrollment)
    db.audit("Enrollment", enrollment["id"], "STATUS_CHANGE",
             auth_role, auth_id,
             {"from_status": old_status, "to_status": "WITHDRAWN"})

    # W2: Refund handling
    if enrollment["payment_status"] == "PAID":
        offering = db.offerings.get(enrollment["offering_id"])
        paid = enrollment["paid_cents"]
        frac = enrollment.get("completion_fraction_bps", 0)

        scheduled = compute_refund_scheduled(paid, frac, reason)
        start_d = _extract_date(offering["start_date"]) if offering else db.today()
        end_d = _extract_date(offering["end_date"]) if offering else db.today()
        statutory = compute_refund_statutory(paid, start_d, end_d, withdrawal_date)
        granted = compute_granted_refund(scheduled, statutory)

        refund_req = db.new_entity({
            "enrollment_id": enrollment["id"],
            "reason": reason,
            "status": "PENDING",
            "completion_fraction_bps_at_withdrawal": frac,
            "scheduled_refund_cents": scheduled,
            "statutory_refund_cents": statutory,
            "granted_refund_cents": granted,
            "denial_reason": None,
            "decided_at": None,
            "paid_at": None,
        })
        db.refund_requests[refund_req["id"]] = refund_req
        db.audit("RefundRequest", refund_req["id"], "REFUND_REQUEST_CREATED",
                 auth_role, auth_id, {})
    elif enrollment["payment_status"] == "PENDING":
        enrollment["payment_status"] = "VOIDED"
        db.touch(enrollment)

    # W3: Recompute offering counts
    offering = db.offerings.get(enrollment["offering_id"])
    if offering:
        update_offering_counts(offering)
        db.touch(offering)


def revoke_certificate_cascade(cert, revoked_reason, auth_role, auth_id):
    """Revoke a certificate and cascade to credit-report amendments."""
    cert["status"] = "REVOKED"
    cert["revoked_reason"] = revoked_reason
    cert["revoked_at"] = db.now_iso()
    db.touch(cert)
    db.audit("Certificate", cert["id"], "CASCADED_REVOCATION",
             auth_role, auth_id,
             {"note": revoked_reason})

    # Cascade: auto-create amendments for ACKNOWLEDGED reports referencing this cert
    for report in list(db.credit_reports.values()):
        if report["status"] != "ACKNOWLEDGED":
            continue
        # Check if this report's line_items reference this cert
        refs_cert = any(li.get("certificate_id") == cert["id"] for li in report.get("line_items", []))
        if not refs_cert:
            continue
        # Check no existing DRAFT/SUBMITTED amendment
        has_open_amendment = any(
            r.get("amendment_of_id") == report["id"] and r["status"] in ("DRAFT", "SUBMITTED")
            for r in db.credit_reports.values()
        )
        if has_open_amendment:
            continue
        # Create amendment
        lines, total = build_amendment_lines(report)
        amendment = db.new_entity({
            "school_id": report["school_id"],
            "period_start": report["period_start"],
            "period_end": report["period_end"],
            "amendment_of_id": report["id"],
            "reason": revoked_reason,
            "status": "DRAFT",
            "line_items": lines,
            "total_credit_hours": total,
            "reporting_deadline_date": report["reporting_deadline_date"],
            "submitted_at": None,
            "late_days": 0,
            "late_fee_cents": 0,
            "submission_count": 0,
        })
        db.credit_reports[amendment["id"]] = amendment
        db.audit("CreditReport", amendment["id"], "AMENDMENT_CREATED",
                 "system", "system",
                 {"note": f"Auto-amendment for revoked certificate {cert['id']}"})


def invalidate_exam_attempt(attempt, reason, auth_role, auth_id):
    """Invalidate an exam attempt; cascade enrollment regression if SCORED-PASSED."""
    old_status = attempt["status"]
    was_passed = attempt.get("outcome") == "PASSED" and old_status == "SCORED"
    enrollment_id = attempt["enrollment_id"]

    attempt["status"] = "INVALIDATED"
    attempt["invalidation_reason"] = reason
    db.touch(attempt)
    db.audit("ExamAttempt", attempt["id"], "STATUS_CHANGE",
             auth_role, auth_id,
             {"from_status": old_status, "to_status": "INVALIDATED",
              "note": reason})

    if was_passed:
        enrollment = db.enrollments.get(enrollment_id)
        if enrollment:
            old_enr_status = enrollment["academic_status"]
            if old_enr_status in ("EXAM_PASSED", "COMPLETED"):
                enrollment["academic_status"] = "SEAT_TIME_MET"
                db.touch(enrollment)
                db.audit("Enrollment", enrollment["id"], "STATUS_CHANGE",
                         "system", "system",
                         {"from_status": old_enr_status, "to_status": "SEAT_TIME_MET"})

                # If was COMPLETED, revoke certificate
                if old_enr_status == "COMPLETED":
                    cert = None
                    for c in db.certificates.values():
                        if c["enrollment_id"] == enrollment["id"] and c["status"] == "ACTIVE":
                            cert = c
                            break
                    if cert:
                        revoke_certificate_cascade(cert, "EXAM_INVALIDATED", "system", "system")
