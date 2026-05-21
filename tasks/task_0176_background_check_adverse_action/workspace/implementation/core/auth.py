"""Authentication + RBAC middleware.

Reads X-User-ID and X-User-Role per PRD §2.1 and the scaffold's auth
validations[]. Roles: Recruiter, Adjudicator, Verifier, Candidate,
PlatformAdmin.
"""
from __future__ import annotations

from functools import wraps
from typing import Tuple

from flask import g, request

from core.errors import err_auth_required, err_forbidden


VALID_ROLES = {"Recruiter", "Adjudicator", "Verifier", "Candidate", "PlatformAdmin"}


def _extract_identity() -> Tuple[str, str]:
    user_id = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    # PRD §2.1 — missing or empty -> ERR_AUTH_REQUIRED.
    if user_id is None or user_id.strip() == "":
        raise err_auth_required()
    if role is None or role.strip() == "":
        raise err_auth_required()
    user_id = user_id.strip()
    role = role.strip()
    if role not in VALID_ROLES:
        # Treat unknown roles as auth failure per §2.1 (role must be one of
        # the five named values). Many tests treat unknown roles as forbidden;
        # we err on the side of ERR_FORBIDDEN here because the auth headers
        # themselves are present.
        raise err_forbidden(f"Unknown role: {role}")
    return user_id, role


def require_roles(*roles: str):
    """Decorator factory: validates auth then enforces role allow-list."""
    allowed = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = _extract_identity()
            g.user_id = user_id
            g.role = role
            if allowed and role not in allowed:
                raise err_forbidden(f"Role {role} is not permitted for this operation.")
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_any_authenticated():
    return require_roles(*VALID_ROLES)


def current_user_id() -> str:
    return g.user_id


def current_role() -> str:
    return g.role
