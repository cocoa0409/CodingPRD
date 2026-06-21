"""Shared route helpers: body parsing/validation, existence lookups,
list slicing, and ordering."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from flask import request

from errors import err

# Stores keyed by entity, used for existence checks (PRD §2.8 left-to-right order).
import db


def get_json_body() -> Dict[str, Any]:
    """Return the request JSON body as a dict, or raise ERR_VALIDATION."""
    if request.method in ("POST", "PUT", "PATCH"):
        data = request.get_json(silent=True)
        if data is None:
            # Allow truly empty bodies for action endpoints (no required fields).
            if not request.data:
                return {}
            raise err("ERR_VALIDATION", "Request body is not valid JSON")
        if not isinstance(data, dict):
            raise err("ERR_VALIDATION", "Request body must be a JSON object")
        return data
    return {}


def require_string(body: Dict[str, Any], field: str) -> str:
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise err("ERR_VALIDATION", f"Field '{field}' must be a non-empty string")
    return val


def require_int(body: Dict[str, Any], field: str) -> int:
    val = body.get(field)
    # Reject bool (subclass of int) and non-int types.
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_VALIDATION", f"Field '{field}' must be an integer")
    return val


def require_number(body: Dict[str, Any], field: str) -> float:
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_VALIDATION", f"Field '{field}' must be a number")
    return float(val)


def require_enum(body: Dict[str, Any], field: str, allowed) -> str:
    val = body.get(field)
    if not isinstance(val, str) or val not in allowed:
        raise err("ERR_VALIDATION", f"Field '{field}' must be one of {sorted(allowed)}")
    return val


def optional_int(body: Dict[str, Any], field: str, default: int) -> int:
    if field not in body or body[field] is None:
        return default
    return require_int(body, field)


def optional_number(body: Dict[str, Any], field: str, default: float) -> float:
    if field not in body or body[field] is None:
        return default
    return require_number(body, field)


def optional_string(body: Dict[str, Any], field: str, default: Optional[str] = None):
    if field not in body or body[field] is None:
        return default
    return require_string(body, field)


# ---- existence lookups ------------------------------------------------------
def get_term(term_id: str) -> Dict[str, Any]:
    rec = db.terms.get(term_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Term not found")
    return rec


def get_student(student_id: str) -> Dict[str, Any]:
    rec = db.students.get(student_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Student not found")
    return rec


def get_program(program_id: str) -> Dict[str, Any]:
    rec = db.programs.get(program_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Program not found")
    return rec


def get_course(course_id: str) -> Dict[str, Any]:
    rec = db.courses.get(course_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Course not found")
    return rec


def get_instructor(instructor_id: str) -> Dict[str, Any]:
    rec = db.instructors.get(instructor_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Instructor not found")
    return rec


def get_section(section_id: str) -> Dict[str, Any]:
    rec = db.sections.get(section_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Section not found")
    return rec


def get_appointment(appointment_id: str) -> Dict[str, Any]:
    rec = db.appointments.get(appointment_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Appointment not found")
    return rec


def get_enrollment(enrollment_id: str) -> Dict[str, Any]:
    rec = db.enrollments.get(enrollment_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Enrollment not found")
    return rec


def get_hold(hold_id: str) -> Dict[str, Any]:
    rec = db.holds.get(hold_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Hold not found")
    return rec


def get_swap_request(swap_id: str) -> Dict[str, Any]:
    rec = db.swap_requests.get(swap_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "SwapRequest not found")
    return rec


# ---- list ordering + slicing ------------------------------------------------
def order_by_created(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Order list results by created_at ascending (PRD §2.3), stable tie-break
    on insertion sequence."""
    return sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))


def paginate(records: List[Dict[str, Any]], limit: int, offset: int):
    """Return (page_slice, total_count)."""
    total = len(records)
    page = records[offset:offset + limit]
    return page, total
