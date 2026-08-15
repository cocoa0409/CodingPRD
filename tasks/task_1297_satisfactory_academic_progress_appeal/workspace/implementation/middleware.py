"""Auth header extraction, role checking, ownership, and request-body helpers."""

from flask import g, request

import errors
from db import store

ROLES = (
    "Student",
    "Registrar",
    "AidOfficer",
    "CommitteeMember",
    "Auditor",
    "AidAdministrator",
)


def authenticate():
    """Priority 1: X-User-ID and X-User-Role present, role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        errors.fail(errors.ERR_UNAUTHENTICATED,
                    "Missing or invalid X-User-ID / X-User-Role headers")
    g.user_id = user_id
    g.user_role = role


def require_roles(*roles):
    """Priority 2: caller role must be in the endpoint's roles list."""
    if g.user_role not in roles:
        errors.fail(errors.ERR_UNAUTHORIZED,
                    "Role %s is not permitted for this endpoint" % g.user_role)


def get_body():
    """Request JSON body as a dict; anything else behaves as an empty body."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def caller_student():
    """Resolve the Student entity behind a Student-role caller, or 404."""
    student = store.students.get(g.user_id)
    if student is None:
        errors.fail(errors.ERR_NOT_FOUND, "Student %s does not exist" % g.user_id)
    return student


def check_student_ownership(student_id):
    """Priority 4: a Student caller may only touch rows whose student_id is theirs."""
    if g.user_role == "Student" and student_id != g.user_id:
        errors.fail(errors.ERR_OWNERSHIP_VIOLATION,
                    "Student callers may only access their own records")


def pagination_params():
    """limit (default 10, 1..100) and offset (default 0, >= 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit, 10) if isinstance(raw_limit, str) else int(raw_limit)
        except (ValueError, TypeError):
            errors.fail(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            errors.fail(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset, 10) if isinstance(raw_offset, str) else int(raw_offset)
        except (ValueError, TypeError):
            errors.fail(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            errors.fail(errors.ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(rows, limit, offset):
    """Sort by creation ascending, then slice; build the pagination block."""
    ordered = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
