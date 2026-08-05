"""Ladder steps 1, 2 and 4 (PRD 2.1 / 2.5)."""

from flask import request

from errors import ApiError

ROLES = (
    "ProgramAdmin",
    "Supervisor",
    "Inspector",
    "IntakeClerk",
    "FinanceOfficer",
    "PropertyOwner",
)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Step 1: both headers present and the role recognised."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return Caller(user_id, role)


def authorize(caller, allowed):
    """Step 2: the acting role appears on the endpoint's authorised list."""
    if caller.role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")
    return caller


def guard(*allowed):
    caller = authenticate()
    authorize(caller, allowed)
    return caller


def require_owner(caller, owner_id):
    """Step 4 for the PropertyOwner role."""
    if caller.role == "PropertyOwner" and caller.user_id != owner_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_officer(caller, officer_id):
    """Step 4 for the Inspector role acting on an inspection."""
    if caller.role == "Inspector" and caller.user_id != officer_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
