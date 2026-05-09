"""Auth middleware: validate X-User-ID / X-User-Role headers."""
from flask import g, request

from errors import raise_api

VALID_ROLES = {"Instructor", "TeachingAssistant", "Student", "AcademicAdmin"}


def extract_auth():
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        raise_api("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "Missing or invalid X-User-ID/X-User-Role headers")
    if not isinstance(user_id, str) or not user_id.strip():
        raise_api("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-ID must be a non-empty string")
    if user_role not in VALID_ROLES:
        raise_api("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  f"Invalid X-User-Role: {user_role}")
    g.user_id = user_id
    g.user_role = user_role
    return user_id, user_role


def require_roles(*allowed):
    user_id, user_role = extract_auth()
    if user_role not in allowed:
        raise_api("ERR_FORBIDDEN_ROLE",
                  f"Role {user_role} not permitted for this endpoint")
    return user_id, user_role
