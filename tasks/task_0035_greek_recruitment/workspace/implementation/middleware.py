from __future__ import annotations

"""Authentication / role middleware."""
from functools import wraps

from flask import g, request

import errors as E


VALID_ROLES = {
    "PanhellenicAdmin",
    "RecruitmentChair",
    "ChapterOfficer",
    "RiskOfficer",
    "PNM",
    "Anonymous",
}


def extract_auth_or_none() -> tuple[str | None, str | None]:
    """Pull X-User-ID / X-User-Role; return (user_id, role) or (None, None) if either is missing."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        return (None, None)
    return (user_id, role)


def require_auth(roles: list[str] | None = None):
    """Decorator: enforce auth + role allow-list. roles=None means any authenticated role.

    Pass roles=["Anonymous"] for a strictly-public endpoint (no headers required at all)
    or roles=["Anonymous", ...] to allow either anonymous or specific authenticated roles.

    Priority order per PRD §2.7:
      1. ERR_UNAUTHENTICATED (401)  - missing/malformed headers
      2. ERR_UNAUTHORIZED   (403)  - headers present but role not allowed for this endpoint
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = extract_auth_or_none()
            allows_anon = roles is not None and "Anonymous" in roles

            if user_id is None:
                # No (or partial) headers present.
                if allows_anon:
                    g.user_id = None
                    g.user_role = "Anonymous"
                    return fn(*args, **kwargs)
                raise E.APIError(E.ERR_UNAUTHENTICATED, "Missing X-User-ID / X-User-Role headers.")

            if role not in VALID_ROLES:
                raise E.APIError(E.ERR_UNAUTHENTICATED, "Malformed X-User-Role.")

            if roles is not None and role not in roles:
                raise E.APIError(E.ERR_UNAUTHORIZED, f"Role {role} not permitted on this endpoint.")

            g.user_id = user_id
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
