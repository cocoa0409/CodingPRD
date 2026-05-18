"""Authentication and RBAC.

PRD §2.1 auth contract:
  - X-User-ID + X-User-Role required on every request.
  - X-User-Role MUST be one of: Member, SecretaryRole, TreasurerRole,
    PresidentRole, DirectorRole.

The PRD's identity rule (X-User-ID is the id of the Member who currently
holds the seat) is enforced at *operation* time — by ownership checks on
the affected resource (payment.member_id == X-User-ID, ACC voter's
board_role membership, etc.) — rather than at the auth layer. This lets
the bootstrap pattern work: the PresidentRole creates the very first
Member before any Member record exists.

Per the test_helpers comments:
  "Implementations must accept a President without an existing Member
   record at first call. Tests use PRESIDENT_BOOTSTRAP_ID for this
   purpose until an election certifies a real Member into the
   PRESIDENT seat."
"""
from __future__ import annotations

from functools import wraps
from typing import Iterable, Tuple

from flask import g, request

from .errors import err_forbidden, err_unauthenticated


VALID_ROLES = {"Member", "SecretaryRole", "TreasurerRole", "PresidentRole", "DirectorRole"}

# Board-role string -> Member.board_role enum value
BOARD_SEAT_FOR_ROLE = {
    "SecretaryRole": "SECRETARY",
    "TreasurerRole": "TREASURER",
    "PresidentRole": "PRESIDENT",
    "DirectorRole": "DIRECTOR",
}


def authenticate() -> Tuple[str, str]:
    """Read X-User-ID + X-User-Role and validate them. Raises APIError on failure.

    Returns (user_id, role). Does NOT require X-User-ID to resolve to an
    existing Member — ownership and seat checks happen at endpoint level.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err_unauthenticated()
    if role not in VALID_ROLES:
        raise err_unauthenticated("Unknown X-User-Role value")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require_roles(allowed: Iterable[str]):
    """Decorator: authenticate then check role membership."""

    allowed_set = set(allowed)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _user_id, role = authenticate()
            if role not in allowed_set:
                raise err_forbidden()
            return fn(*args, **kwargs)

        return wrapper

    return deco


def current_user() -> Tuple[str, str]:
    return g.user_id, g.user_role
