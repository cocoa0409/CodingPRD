"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- PlatformAdmin is OPAQUE: 'X-User-ID for this role is an opaque
  operator identifier that is not tied to any persisted entity in the
  system'. Shared constants are safe.

- LabOwner is ENTITY-BACKED on the User table: 'When X-User-Role is
  LabOwner, X-User-ID is the id of the acting User; ownership checks on
  any Lab compare the lab's contact_user_id to X-User-ID, and ownership
  checks on any Equipment, BillingRule, MaintenanceWindow, Authorization,
  or Reservation resolve to the lab through Equipment.lab_id'.

- User is ENTITY-BACKED on the User table: 'When X-User-Role is User,
  X-User-ID is the id of the acting User; ownership checks on
  Authorization and Reservation compare the resource's user_id foreign
  key to X-User-ID'.

For entity-backed roles, every ownership-gated call MUST use the
per-instance builder make_lab_owner_headers(user['id']) or
make_user_headers(user['id']) — passing the shared fallback constant
will fail PRD §2.1 ownership checks for any real entity id, cascading
'Setup failed' across the test suite.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared opaque-role constants and non-binding entity-backed fallbacks.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # PlatformAdmin — opaque, canonical constant is correct.
    "platform_admin_headers": build_user_headers(
        "platform-admin-001", "PlatformAdmin",
    ),
    "platform_admin_headers_alt": build_user_headers(
        "platform-admin-002", "PlatformAdmin",
    ),
    # LabOwner fallback — entity-backed; use ONLY for tests that do not
    # exercise ownership (missing-headers / wrong-role / 404 / 400
    # scenarios). Per PRD §2.1, ownership-gated calls MUST switch to
    # make_lab_owner_headers(user['id']).
    "lab_owner_headers": build_user_headers(
        "lab-owner-fallback", "LabOwner",
    ),
    # User fallback — entity-backed; same caveat as LabOwner.
    "user_headers": build_user_headers(
        "user-fallback", "User",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders. Required for the entity_backed LabOwner and User
# roles. Pass the User.id returned by POST /users (or the User.id stored
# as lab.contact_user_id for the LabOwner role).
# ---------------------------------------------------------------------------
def make_lab_owner_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is LabOwner, X-User-ID is the id of the
    acting User; ownership checks ... compare the lab's contact_user_id
    to X-User-ID'. Pass the actual User.id that owns the lab."""
    return build_user_headers(user_id, "LabOwner")


def make_user_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is User, X-User-ID is the id of the
    acting User'. Pass the actual User.id whenever the call is
    ownership-gated (POST /reservations, /check-in, /check-out, /cancel,
    POST /authorizations)."""
    return build_user_headers(user_id, "User")


def make_platform_admin_headers(admin_id: str = "platform-admin-001"
                                 ) -> Dict[str, str]:
    """PRD §2.1: 'PlatformAdmin ... X-User-ID for this role is an opaque
    operator identifier'."""
    return build_user_headers(admin_id, "PlatformAdmin")


__all__ = [
    "TEST_USERS",
    "make_lab_owner_headers",
    "make_user_headers",
    "make_platform_admin_headers",
]
