"""Auth header extraction, role checking, and request-body helpers.

Auth headers (PRD §2.1):
  X-User-ID    — identifies the acting user
  X-User-Role  — one of RmaAdmin, Agent, LossAdjuster
"""
from flask import request

import errors

VALID_ROLES = {"RmaAdmin", "Agent", "LossAdjuster"}


def authenticate():
    """Validate the auth headers (priority 1). Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED,
                         "Missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def require_role(role, allowed):
    """Role authorization (priority 2)."""
    if role not in allowed:
        raise errors.err(errors.ERR_FORBIDDEN,
                         "Acting role %s is not permitted for this operation" % role)


def get_json():
    """Return the parsed JSON body, or {} if none/invalid."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data
