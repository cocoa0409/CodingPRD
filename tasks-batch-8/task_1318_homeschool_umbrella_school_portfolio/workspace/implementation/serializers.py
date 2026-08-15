"""Entity -> public JSON serialization."""
from decimal import Decimal


def _base(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_academic_year(r):
    d = _base(r)
    d.update({
        "label": r["label"],
        "start_date": r["start_date"],
        "end_date": r["end_date"],
        "notice_filing_deadline": r["notice_filing_deadline"],
        "portfolio_due_date": r["portfolio_due_date"],
        "state_report_due_date": r["state_report_due_date"],
        "mid_year_date": r["mid_year_date"],
        "testing_grades": list(r["testing_grades"]),
        "required_instructional_days": r["required_instructional_days"],
        "required_minutes_elementary": r["required_minutes_elementary"],
        "required_minutes_secondary": r["required_minutes_secondary"],
        "status": r["status"],
    })
    return d


def ser_family(r):
    d = _base(r)
    d.update({
        "display_name": r["display_name"],
        "district_code": r["district_code"],
        "fee_balance_cents": r["fee_balance_cents"],
        "oldest_unpaid_charge_at": r["oldest_unpaid_charge_at"],
        "fee_status": r["fee_status"],
    })
    return d


def ser_student(r):
    d = _base(r)
    d.update({
        "family_id": r["family_id"],
        "full_name": r["full_name"],
        "date_of_birth": r["date_of_birth"],
        "transcript_sealed": r["transcript_sealed"],
        "sealed_at": r["sealed_at"],
        "diploma_number": r["diploma_number"],
    })
    return d


def ser_enrollment(r):
    d = _base(r)
    d.update({
        "student_id": r["student_id"],
        "academic_year_id": r["academic_year_id"],
        "grade_level": r["grade_level"],
        "enrollment_status": r["enrollment_status"],
        "compliance_standing": r["compliance_standing"],
        "standing_locked": r["standing_locked"],
        "provisional_days_counted": r["provisional_days_counted"],
        "provisional_minutes_credited": r["provisional_minutes_credited"],
        "certified_days_counted": r["certified_days_counted"],
        "certified_minutes_credited": r["certified_minutes_credited"],
        "testing_required": r["testing_required"],
        "testing_satisfied": r["testing_satisfied"],
        "activated_at": r["activated_at"],
        "withdrawn_at": r["withdrawn_at"],
    })
    return d


def ser_notice(r):
    d = _base(r)
    d.update({
        "enrollment_id": r["enrollment_id"],
        "district_code": r["district_code"],
        "status": r["status"],
        "filed_at": r["filed_at"],
        "acknowledged_at": r["acknowledged_at"],
        "returned_reason": r["returned_reason"],
        "refile_count": r["refile_count"],
    })
    return d


def ser_curriculum_plan(r):
    d = _base(r)
    d.update({
        "enrollment_id": r["enrollment_id"],
        "subjects": list(r["subjects"]),
        "status": r["status"],
        "revision_count": r["revision_count"],
        "reviewer_id": r["reviewer_id"],
        "review_notes": r["review_notes"],
    })
    return d


def ser_attendance_entry(r):
    d = _base(r)
    d.update({
        "enrollment_id": r["enrollment_id"],
        "entry_date": r["entry_date"],
        "minutes": r["minutes"],
        "status": r["status"],
        "verified_by": r["verified_by"],
    })
    return d


def ser_portfolio(r):
    d = _base(r)
    d.update({
        "enrollment_id": r["enrollment_id"],
        "status": r["status"],
        "attempt_count": r["attempt_count"],
        "submitted_at": r["submitted_at"],
        "decided_at": r["decided_at"],
    })
    return d


def ser_evaluation(r):
    # Evaluation is immutable: only id and created_at
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "portfolio_id": r["portfolio_id"],
        "reviewer_id": r["reviewer_id"],
        "attempt_number": r["attempt_number"],
        "overall_outcome": r["overall_outcome"],
        "subject_scores": [dict(s) for s in r["subject_scores"]],
        "notes": r["notes"],
    }


def ser_exam_session(r):
    d = _base(r)
    d.update({
        "academic_year_id": r["academic_year_id"],
        "test_name": r["test_name"],
        "session_date": r["session_date"],
        "start_minutes": r["start_minutes"],
        "end_minutes": r["end_minutes"],
        "capacity": r["capacity"],
        "registration_deadline": r["registration_deadline"],
        "target_grades": list(r["target_grades"]),
        "location": r["location"],
        "seats_taken": r["seats_taken"],
        "status": r["status"],
    })
    return d


def ser_test_registration(r):
    d = _base(r)
    d.update({
        "enrollment_id": r["enrollment_id"],
        "exam_session_id": r["exam_session_id"],
        "status": r["status"],
        "composite_percentile": r["composite_percentile"],
        "passed": r["passed"],
        "exemption_note": r["exemption_note"],
    })
    return d


def ser_course_credit(r):
    d = _base(r)
    d.update({
        "enrollment_id": r["enrollment_id"],
        "subject": r["subject"],
        "course_title": r["course_title"],
        "is_lab": r["is_lab"],
        "planned_hours": r["planned_hours"],
        "completed_hours": r["completed_hours"],
        "letter_grade": r["letter_grade"],
        "credit_value": float(r["credit_value"]) if r["credit_value"] is not None else None,
        "status": r["status"],
        "posted_at": r["posted_at"],
        "revoked_reason": r["revoked_reason"],
    })
    return d


def ser_coop_class(r):
    d = _base(r)
    d.update({
        "academic_year_id": r["academic_year_id"],
        "title": r["title"],
        "subject": r["subject"],
        "grade_min": r["grade_min"],
        "grade_max": r["grade_max"],
        "meeting_day": r["meeting_day"],
        "meeting_start_minutes": r["meeting_start_minutes"],
        "meeting_end_minutes": r["meeting_end_minutes"],
        "start_date": r["start_date"],
        "end_date": r["end_date"],
        "capacity": r["capacity"],
        "fee_base_cents": r["fee_base_cents"],
        "materials_fee_cents": r["materials_fee_cents"],
        "seats_taken": r["seats_taken"],
        "status": r["status"],
    })
    return d


def ser_coop_enrollment(r):
    d = _base(r)
    d.update({
        "enrollment_id": r["enrollment_id"],
        "coop_class_id": r["coop_class_id"],
        "status": r["status"],
        "fee_cents": r["fee_cents"],
        "discount_pct_applied": r["discount_pct_applied"],
        "refund_cents": r["refund_cents"],
        "drop_reason": r["drop_reason"],
        "promoted_at": r["promoted_at"],
    })
    return d


def ser_graduation_application(r):
    d = _base(r)
    d.update({
        "student_id": r["student_id"],
        "academic_year_id": r["academic_year_id"],
        "status": r["status"],
        "evaluated_by": r["evaluated_by"],
        "decision_notes": r["decision_notes"],
        "diploma_issued_at": r["diploma_issued_at"],
    })
    return d


def ser_compliance_report(r):
    d = _base(r)
    d.update({
        "academic_year_id": r["academic_year_id"],
        "status": r["status"],
        "generated_at": r["generated_at"],
        "submitted_at": r["submitted_at"],
        "late": r["late"],
        "total_enrollments": r["total_enrollments"],
        "compliant_count": r["compliant_count"],
        "noncompliant_enrollment_ids": list(r["noncompliant_enrollment_ids"]),
        "rejection_reason": r["rejection_reason"],
    })
    return d


def credit_to_float(dec):
    return float(dec) if dec is not None else None
