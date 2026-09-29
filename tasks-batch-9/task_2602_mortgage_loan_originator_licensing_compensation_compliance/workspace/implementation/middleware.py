"""Auth header extraction, role gating and originator-identity ownership.

Validation priorities 1-4 of PRD 2.9 live here:
  1 ERR_MISSING_AUTH_HEADERS (401)
  2 ERR_UNKNOWN_ROLE (401)
  3 ERR_ROLE_NOT_PERMITTED (403)
  4 ERR_ORIGINATOR_IDENTITY_MISMATCH (403)
"""
import functools

from flask import g, request

from errors import ApiError

ROLES = (
    "LicensingAnalyst",
    "CompensationDesigner",
    "ComplianceOfficer",
    "Originator",
    "LoanOperations",
    "ExaminationCoordinator",
    "PlatformAdmin",
)
# Every GET in this API is shared by all seven roles.
ALL_ROLES = ROLES


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or str(user_id).strip() == "" or str(role).strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    user_id = str(user_id).strip()
    role = str(role).strip()
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def endpoint(*allowed_roles):
    """Route decorator performing priorities 1-3."""
    roles = tuple(allowed_roles)

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate(roles)
            return fn(*args, **kwargs)
        return wrapper
    return deco


def require_identity(originator_id):
    """Priority 4. Only applied on the write endpoints whose authorised role
    set includes Originator; shared reads are exempt (PRD 2.1)."""
    if g.role != "Originator":
        return
    if originator_id is None:
        return
    if g.user_id != originator_id:
        raise ApiError("ERR_ORIGINATOR_IDENTITY_MISMATCH")


def identity_from_body(body, field="originator_id"):
    """Priority 4 for creates: compare X-User-ID against the body's
    originator_id. Only enforced when the field is actually supplied as a
    string; an absent/mistyped field falls through to priority 7."""
    if g.role != "Originator":
        return
    if not isinstance(body, dict):
        return
    value = body.get(field)
    if isinstance(value, str):
        if g.user_id != value:
            raise ApiError("ERR_ORIGINATOR_IDENTITY_MISMATCH")
