"""Serializers: convert stored records to client-facing JSON.

Each serializer projects exactly the entity's declared fields plus the common
system fields it carries. Internal bookkeeping keys (those prefixed with `_`)
are never exposed.
"""
from __future__ import annotations

from typing import Any, Dict


def _common(rec: Dict[str, Any], out: Dict[str, Any]) -> Dict[str, Any]:
    out["id"] = rec["id"]
    out["created_at"] = rec["created_at"]
    if "updated_at" in rec:
        out["updated_at"] = rec["updated_at"]
    if "version" in rec:
        out["version"] = rec["version"]
    return out


def term(rec: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "name": rec["name"],
        "registration_opens_at": rec["registration_opens_at"],
        "add_deadline": rec["add_deadline"],
        "drop_deadline": rec["drop_deadline"],
        "withdraw_deadline": rec["withdraw_deadline"],
        "refund_full_pct": rec["refund_full_pct"],
        "refund_partial_pct": rec["refund_partial_pct"],
        "per_credit_cost_cents": rec["per_credit_cost_cents"],
        "status": rec["status"],
    }
    return _common(rec, out)


def program(rec: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "name": rec["name"],
        "required_credit_hours": rec["required_credit_hours"],
        "min_gpa": rec["min_gpa"],
    }
    return _common(rec, out)


def course(rec: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "code": rec["code"],
        "title": rec["title"],
        "credit_hours": rec["credit_hours"],
        "program_id": rec["program_id"],
        "is_active": rec["is_active"],
    }
    return _common(rec, out)


def course_requirement(rec: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "course_id": rec["course_id"],
        "required_course_id": rec["required_course_id"],
        "requirement_type": rec["requirement_type"],
        "min_grade_points": rec["min_grade_points"],
    }
    return _common(rec, out)


def instructor(rec: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "full_name": rec["full_name"],
        "email": rec["email"],
        "gap_minutes": rec["gap_minutes"],
    }
    return _common(rec, out)


def section(rec: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "term_id": rec["term_id"],
        "course_id": rec["course_id"],
        "instructor_id": rec["instructor_id"],
        "section_code": rec["section_code"],
        "seat_capacity": rec["seat_capacity"],
        "seats_taken": rec["seats_taken"],
        "waitlist_capacity": rec["waitlist_capacity"],
        "waitlist_count": rec["waitlist_count"],
        "meeting_days": rec["meeting_days"],
        "meeting_start_min": rec["meeting_start_min"],
        "meeting_end_min": rec["meeting_end_min"],
        "status": rec["status"],
    }
    return _common(rec, out)


def student(rec: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "full_name": rec["full_name"],
        "email": rec["email"],
        "program_id": rec["program_id"],
        "completed_credit_hours": rec["completed_credit_hours"],
        "earned_credit_hours": rec["earned_credit_hours"],
        "gpa": rec["gpa"],
        "academic_standing": rec["academic_standing"],
        "tuition_owed_cents": rec["tuition_owed_cents"],
    }
    return _common(rec, out)


def appointment(rec: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "term_id": rec["term_id"],
        "student_id": rec["student_id"],
        "priority_tier": rec["priority_tier"],
        "window_opens_at": rec["window_opens_at"],
        "max_credit_hours": rec["max_credit_hours"],
        "enrolled_credit_hours": rec["enrolled_credit_hours"],
    }
    return _common(rec, out)


def enrollment(rec: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "term_id": rec["term_id"],
        "student_id": rec["student_id"],
        "section_id": rec["section_id"],
        "registration_status": rec["registration_status"],
        "grade_status": rec["grade_status"],
        "letter_grade": rec["letter_grade"],
        "grade_points": rec["grade_points"],
        "tuition_charged_cents": rec["tuition_charged_cents"],
        "refund_cents": rec["refund_cents"],
        "waitlist_position": rec["waitlist_position"],
    }
    return _common(rec, out)


def hold(rec: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "student_id": rec["student_id"],
        "hold_type": rec["hold_type"],
        "reason": rec["reason"],
        "status": rec["status"],
    }
    return _common(rec, out)


def swap_request(rec: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "student_id": rec["student_id"],
        "term_id": rec["term_id"],
        "drop_enrollment_id": rec["drop_enrollment_id"],
        "add_section_id": rec["add_section_id"],
        "status": rec["status"],
        "added_enrollment_id": rec["added_enrollment_id"],
    }
    return _common(rec, out)


def refund_transaction(rec: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "enrollment_id": rec["enrollment_id"],
        "student_id": rec["student_id"],
        "refund_tier": rec["refund_tier"],
        "amount_cents": rec["amount_cents"],
        "triggered_by": rec["triggered_by"],
    }
    return _common(rec, out)
