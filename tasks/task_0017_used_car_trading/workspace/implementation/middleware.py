"""Auth middleware: validate X-User-ID and X-User-Role on every request."""

import re
import uuid

from flask import g, request

from errors import err

VALID_ROLES = {"Seller", "Buyer", "Inspector", "PlatformAdmin"}


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except Exception:
        return False


def _is_nonempty_id(value: str) -> bool:
    """Identity for opaque actors (Inspector, PlatformAdmin) need not be a UUID,
    but must be present and printable. For Seller/Buyer, treat as UUID per PRD."""
    if not isinstance(value, str):
        return False
    s = value.strip()
    if not s:
        return False
    return True


# Endpoints exempt from auth (none here, but the framework supports it).
EXEMPT_PATHS = set()


def auth_required():
    """Run on every request. Sets g.user_id, g.role; raises APIError on failure."""
    if request.method == "OPTIONS":
        return None
    if request.path in EXEMPT_PATHS:
        return None

    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    # 1) ERR_AUTH_MISSING — either header missing
    if user_id is None or role is None:
        raise err("ERR_AUTH_MISSING", "Missing X-User-ID or X-User-Role header")

    # 2) ERR_AUTH_INVALID — unrecognized role / empty / malformed UUID
    if role not in VALID_ROLES:
        raise err("ERR_AUTH_INVALID", f"Unrecognized role '{role}'")

    if not _is_nonempty_id(user_id):
        raise err("ERR_AUTH_INVALID", "X-User-ID must be non-empty")

    # PRD §2.1: an X-User-ID that is empty or not a well-formed UUID yields ERR_AUTH_INVALID.
    if not _is_uuid(user_id.strip()):
        raise err("ERR_AUTH_INVALID", "X-User-ID must be a well-formed UUID")

    g.user_id = user_id.strip()
    g.role = role
    return None


def require_role(*allowed_roles):
    if g.role not in allowed_roles:
        raise err("ERR_FORBIDDEN", f"Role '{g.role}' not permitted")
