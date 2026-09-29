"""Shared route helpers."""

from flask import g

from errors import ApiError


def require_owner(owner_id):
    """Ownership for the entity-backed roles (PRD sec 2.1, gauntlet step 5)."""
    if g.user_id != owner_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_state(condition, error_id):
    if not condition:
        raise ApiError(error_id)


def acting_user():
    return g.user_id
