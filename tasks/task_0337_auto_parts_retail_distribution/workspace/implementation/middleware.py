"""Auth header extraction, role checking, and shared request validation.

PRD §2.1: every request must carry X-User-ID and X-User-Role. The four valid
roles are CounterClerk, WholesaleRep, InventoryManager, WarrantyAdmin. Identity
is opaque — X-User-ID is never compared to any entity id.
"""
from __future__ import annotations

from flask import request

from errors import (
    APIError,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_REQUEST,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
)

VALID_ROLES = {"CounterClerk", "WholesaleRep", "InventoryManager", "WarrantyAdmin"}


def require_auth() -> str:
    """Validate auth headers (priority 1). Returns the role on success."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise APIError(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 401)
    if not role or role not in VALID_ROLES:
        raise APIError(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 401)
    return role


def require_role(*allowed_roles: str) -> str:
    """Validate auth (priority 1) then role permission (priority 2)."""
    role = require_auth()
    if role not in allowed_roles:
        raise APIError(ERR_INSUFFICIENT_PERMISSIONS, 403)
    return role


def get_body() -> dict:
    """Parse the JSON body. Missing or malformed bodies are treated as {}.

    A non-object JSON payload is an invalid request.
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise APIError(ERR_INVALID_REQUEST, 422, "Request body must be a JSON object")
    return body
