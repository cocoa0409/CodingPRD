"""Rejection-ladder rungs 1-4: authentication, role authorization, existence,
ownership (PRD sections 2.1, 2.6, 2.7)."""

from flask import request

import constants as C
from errors import fail
from store import store

NOT_FOUND_ERRORS = {
    "business_lines": "ERR_BUSINESS_LINE_NOT_FOUND",
    "referral_partners": "ERR_REFERRAL_PARTNER_NOT_FOUND",
    "referrals": "ERR_REFERRAL_NOT_FOUND",
    "participants": "ERR_PARTICIPANT_NOT_FOUND",
    "work_shifts": "ERR_WORK_SHIFT_NOT_FOUND",
    "shift_assignments": "ERR_SHIFT_ASSIGNMENT_NOT_FOUND",
    "support_activities": "ERR_SUPPORT_ACTIVITY_NOT_FOUND",
    "employers": "ERR_EMPLOYER_NOT_FOUND",
    "placements": "ERR_PLACEMENT_NOT_FOUND",
    "retention_checkpoints": "ERR_RETENTION_CHECKPOINT_NOT_FOUND",
    "subsidy_periods": "ERR_SUBSIDY_PERIOD_NOT_FOUND",
    "cost_entries": "ERR_COST_ENTRY_NOT_FOUND",
}


def authenticate():
    """Rung 1.  Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in C.ROLES:
        fail("ERR_UNAUTHENTICATED")
    return user_id, role


def authorize(role, allowed_roles):
    """Rung 2."""
    if role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED")


def require(allowed_roles):
    """Rungs 1 and 2 together.  Returns (user_id, role)."""
    user_id, role = authenticate()
    authorize(role, allowed_roles)
    return user_id, role


def must_get(kind, object_id):
    """Rung 3 for a single identifier."""
    record = None
    if isinstance(object_id, str):
        record = getattr(store, kind).get(object_id)
    if record is None:
        fail(NOT_FOUND_ERRORS[kind])
    return record


def must_exist_filter(kind, object_id):
    """Rung 3 for an identifier supplied as a collection filter."""
    if object_id is None or object_id == "":
        return None
    return must_get(kind, object_id)


def require_owner(expected_owner_id, user_id):
    """Rung 4."""
    if expected_owner_id != user_id:
        fail("ERR_NOT_RESOURCE_OWNER")
