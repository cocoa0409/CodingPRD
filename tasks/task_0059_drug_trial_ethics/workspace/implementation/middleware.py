from __future__ import annotations

"""Auth header extraction + role-based access control checks."""

from flask import g, request

from errors import (
    APIError,
    ERR_AUTH_INVALID,
    ERR_AUTH_MISSING,
    ERR_FORBIDDEN,
    raise_error,
)


VALID_ROLES = {"Applicant", "Secretary", "Chairperson", "CommitteeMember", "RegulatoryWatcher"}


def auth_required():
    """Extract X-User-ID and X-User-Role headers; populate flask.g."""
    user_id = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    if not user_id or not role:
        raise_error(ERR_AUTH_MISSING, "X-User-ID and X-User-Role headers are required")
    if role not in VALID_ROLES:
        raise_error(ERR_AUTH_INVALID, f"X-User-Role '{role}' is not a recognised role")
    g.user_id = user_id
    g.user_role = role


def require_role(allowed: set[str]):
    if g.user_role not in allowed:
        raise_error(ERR_FORBIDDEN, f"Role '{g.user_role}' may not perform this action")


def ensure_owns_application(application: dict):
    """For Applicant-write actions, X-User-ID must match Application.applicant_id."""
    if g.user_role == "Applicant" and application.get("applicant_id") != g.user_id:
        raise_error(ERR_FORBIDDEN, "Caller is not the applicant of this application")


def ensure_acting_member_exists():
    """For roles backed by a CommitteeMember (Chairperson, CommitteeMember),
    X-User-ID must point at an existing committee member that is currently
    active (for Chairperson) or that exists (for CommitteeMember actions —
    attendance/vote endpoints also check is_active downstream)."""
    from db import committee_members
    member = committee_members.get(g.user_id)
    if member is None:
        raise_error(ERR_FORBIDDEN, "Caller is not a known committee member")
    return member
