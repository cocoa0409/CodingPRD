"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- PlatformAdmin, StaffOps, and system carry OPAQUE X-User-IDs. The PRD
  states the server "may record it on audit entries" but "does not compare
  it to any entity's id." Shared constants are safe for these roles in all
  tests.

- Member and Trainer are ENTITY-BACKED. PRD §2.1:
    "When X-User-Role is Member, X-User-ID is the id of the acting Member;
     ownership checks on any resource that references a Member compare the
     resource's foreign-key field ... to X-User-ID, and a mismatch is
     rejected with ERR_FORBIDDEN."
    "When X-User-Role is Trainer, X-User-ID is the id of the acting
     Trainer; ownership checks ... compare its trainer foreign key ... to
     X-User-ID."

  Every ownership-gated Member-role or Trainer-role call therefore MUST
  use make_member_headers(member['id']) / make_trainer_headers(
  trainer['id']) with the actual entity's id. Falling back to the shared
  constant guarantees the ownership check fails for any real entity id,
  cascading "Setup failed" into every downstream test.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared opaque-role constants (PRD §2.1: PlatformAdmin / StaffOps / system).
# Plus non-binding fallbacks for entity-backed roles, used only for tests
# that do not exercise ownership.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — canonical constants.
    "platform_admin_headers": build_user_headers(
        "platform-admin-001", "PlatformAdmin",
    ),
    "platform_admin_headers_alt": build_user_headers(
        "platform-admin-002", "PlatformAdmin",
    ),
    "staff_ops_headers": build_user_headers(
        "staff-ops-001", "StaffOps",
    ),
    "staff_ops_headers_alt": build_user_headers(
        "staff-ops-002", "StaffOps",
    ),
    "system_headers": build_user_headers(
        "system-runner", "system",
    ),
    # Entity-backed fallbacks — use ONLY for tests that do not exercise
    # ownership (missing-auth, wrong-role, missing-resource scenarios). The
    # real X-User-ID must equal the persisted entity id; the per-instance
    # builders below are the correct path in fixtures.
    "member_headers": build_user_headers(
        "member-fallback", "Member",
    ),
    "trainer_headers": build_user_headers(
        "trainer-fallback", "Trainer",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders. Required for the entity_backed Member and Trainer
# roles whenever the downstream call is ownership-gated.
# ---------------------------------------------------------------------------
def make_member_headers(member_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Member, X-User-ID is the id of the
    acting Member.' Pass the actual Member.id whenever the downstream call
    exercises an ownership check (wallet recharge, card freeze, booking
    cancel, member-self PATCH, etc.)."""
    return build_user_headers(member_id, "Member")


def make_trainer_headers(trainer_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Trainer, X-User-ID is the id of the
    acting Trainer.' Pass the actual Trainer.id whenever the downstream
    call exercises an ownership check (publish own slot, complete own
    booking, read own commissions)."""
    return build_user_headers(trainer_id, "Trainer")


def make_platform_admin_headers(
    user_id: str = "platform-admin-001",
) -> Dict[str, str]:
    """PRD §2.1: PlatformAdmin X-User-ID is an opaque operator id."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_staff_ops_headers(
    user_id: str = "staff-ops-001",
) -> Dict[str, str]:
    """PRD §2.1: StaffOps X-User-ID is an opaque operator id."""
    return build_user_headers(user_id, "StaffOps")


def make_system_headers(
    user_id: str = "system-runner",
) -> Dict[str, str]:
    """PRD §2.1: system X-User-ID is an opaque internal identifier."""
    return build_user_headers(user_id, "system")


__all__ = [
    "TEST_USERS",
    "make_member_headers",
    "make_trainer_headers",
    "make_platform_admin_headers",
    "make_staff_ops_headers",
    "make_system_headers",
]
