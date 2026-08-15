"""Authentication / role authorization (validation priorities 1 and 2)."""

from flask import request

from errors import ApiError

ROLES = {"FacultyProposer", "DepartmentChair", "CurriculumCommittee", "FacultySenate", "Registrar"}

ANY_ROLE = None  # every authenticated role


def require_auth(allowed_roles=ANY_ROLE):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing X-User-Role/X-User-ID headers or unknown role")
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN", 403, "role not authorized for this endpoint")
    return uid, role
