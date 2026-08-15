"""Auth header extraction, role checking, and entity-backed ownership helpers."""

from flask import request

import errors

ROLES = {"SchoolAdmin", "FrontOfficeStaff", "Teacher", "FamilyGuardian", "Interpreter"}
STAFF = {"SchoolAdmin", "FrontOfficeStaff"}


def get_auth():
    """Validate X-User-ID / X-User-Role headers. Returns (role, user_id)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str):
        raise errors.unauthenticated()
    if not role or role not in ROLES:
        raise errors.unauthenticated()
    return role, user_id


def require_roles(role, allowed):
    if role not in allowed:
        raise errors.forbidden("Role not allowed on this endpoint")


def is_staff(role):
    return role in STAFF


def check_family_owns(role, user_id, family_id):
    if role == "FamilyGuardian" and user_id != family_id:
        raise errors.forbidden("FamilyGuardian may act only on their own family")


def check_teacher_owns(role, user_id, teacher_id):
    if role == "Teacher" and user_id != teacher_id:
        raise errors.forbidden("Teacher may act only on their own resources")


def check_interpreter_owns(role, user_id, interpreter_id):
    if role == "Interpreter" and user_id != interpreter_id:
        raise errors.forbidden("Interpreter may act only on their own requests")
