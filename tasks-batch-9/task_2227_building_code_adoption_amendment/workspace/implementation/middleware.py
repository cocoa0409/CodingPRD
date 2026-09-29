"""Authentication, RBAC and identity resolution — ladder priorities 1, 2 and 3."""
from flask import request

import config
import db
from errors import ApiError


def authenticate():
    """Priority 1: both identity headers must be present and non-blank."""
    user_id = request.headers.get(config.HEADER_USER_ID)
    role = request.headers.get(config.HEADER_USER_ROLE)
    if role is None or not str(role).strip():
        role = request.headers.get(config.HEADER_USER_ROLE_FALLBACK)
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id.strip(), role.strip()


def authorize(role, allowed_roles):
    """Priority 2: the role must be a recognised role permitted on this endpoint."""
    if role not in config.ALL_ROLES or role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")


def require(allowed_roles):
    user_id, role = authenticate()
    authorize(role, allowed_roles)
    return user_id, role


def resolve_identity(user_id, role):
    """Priority 3: entity-backed roles must resolve to a live backing row."""
    if role in config.MEMBER_BACKED_ROLES:
        member = db.committee_members.get(user_id)
        if member is None:
            raise ApiError("ERR_IDENTITY_NOT_FOUND")
        return member
    if role in config.JURISDICTION_BACKED_ROLES:
        jurisdiction = db.jurisdictions.get(user_id)
        if jurisdiction is None:
            raise ApiError("ERR_IDENTITY_NOT_FOUND")
        return jurisdiction
    return None
