"""Auth header extraction and role validation per PRD §2.1 and §2.6 priorities 1-3."""

from flask import g, request

from errors import (
    ERR_INVALID_ROLE,
    ERR_MISSING_AUTH,
    ERR_UNAUTHORIZED,
    raise_api,
)


VALID_ROLES = {"PlanAdministrator", "AccountOwner", "IRSAuditor"}


def parse_auth_headers():
    """Run priorities 1 and 2 from PRD §2.6 — must be invoked at the start of
    every routed endpoint. Stashes (role, user_id) on flask.g."""
    role = request.headers.get("X-User-Role")
    if role is None or role == "":
        raise_api(ERR_MISSING_AUTH)
    if role not in VALID_ROLES:
        raise_api(ERR_INVALID_ROLE)
    user_id = request.headers.get("X-User-ID")
    # X-User-ID is mandatory for AccountOwner-scoped operations (validated later
    # at the per-endpoint check via require_account_owner_match), but otherwise
    # may be opaque.
    g.role = role
    g.user_id = user_id


def require_roles(*allowed_roles):
    """Priority 3: caller's role must be in the allowed set."""
    if g.role not in allowed_roles:
        raise_api(ERR_UNAUTHORIZED)


def require_owner_match(owner_id_required: str):
    """For AccountOwner callers, the X-User-ID header must match the resource's
    owner_id. PlanAdministrator and IRSAuditor are opaque and skip this check."""
    if g.role == "AccountOwner":
        if g.user_id is None or g.user_id == "":
            raise_api(ERR_UNAUTHORIZED)
        if g.user_id != owner_id_required:
            raise_api(ERR_UNAUTHORIZED)
