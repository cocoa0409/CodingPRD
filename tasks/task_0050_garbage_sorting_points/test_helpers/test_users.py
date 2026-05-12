"""Pre-built role headers for every role in the PRD.

Three roles are opaque (PRD §2.1): SystemOperator, CommunityAdmin,
AppealReviewer. For these, X-User-ID is an opaque operator identifier not
tied to any persisted entity, so shared constants are canonical.

One role is entity-backed: Resident. PRD §2.1: 'When X-User-Role is
Resident, X-User-ID is the id of the acting Resident entity; ownership
checks on any resource that references a Resident compare the resource's
resident_id foreign-key field to X-User-ID, and household membership is
enforced by requiring that the Resident referenced by X-User-ID has a
household_id matching the path's household.'  Therefore every
ownership-gated Resident call (disposal create, redemption submit,
violation appeal, household-scoped reads) MUST be issued via
make_resident_headers(resident_id) with the real Resident.id.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Shared constants. Safe ONLY when:
#   - the role is opaque (SystemOperator, CommunityAdmin, AppealReviewer), or
#   - the test does NOT exercise an ownership check
#     (e.g., RBAC permission-denied, 400 on bad payload, 404 on missing path).
# For ownership-gated Resident calls, ALWAYS use make_resident_headers().
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — shared constants are canonical (PRD §2.1).
    "system_operator_headers": build_user_headers(
        "op-system-001", "SystemOperator",
    ),
    "community_admin_headers": build_user_headers(
        "op-admin-001", "CommunityAdmin",
    ),
    "appeal_reviewer_headers": build_user_headers(
        "op-reviewer-001", "AppealReviewer",
    ),
    # Entity-backed fallback — do NOT use for ownership-gated Resident calls.
    "resident_fallback_headers": build_user_headers(
        "resident-fallback", "Resident",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders. For Resident, X-User-ID MUST be the resident's
# Resident.id; failing to thread the real id makes ownership checks
# (resident_id == X-User-ID, household membership) reject every request.
# ---------------------------------------------------------------------------
def make_resident_headers(resident_id: str) -> Dict[str, str]:
    """Resident is entity_backed:Resident (PRD §2.1).
    For ownership-gated calls, X-User-ID must equal the acting Resident.id."""
    return build_user_headers(resident_id, "Resident")


def make_system_operator_headers(
    actor_id: str = "op-system-001",
) -> Dict[str, str]:
    """SystemOperator is opaque (PRD §2.1)."""
    return build_user_headers(actor_id, "SystemOperator")


def make_community_admin_headers(
    actor_id: str = "op-admin-001",
) -> Dict[str, str]:
    """CommunityAdmin is opaque (PRD §2.1)."""
    return build_user_headers(actor_id, "CommunityAdmin")


def make_appeal_reviewer_headers(
    actor_id: str = "op-reviewer-001",
) -> Dict[str, str]:
    """AppealReviewer is opaque (PRD §2.1)."""
    return build_user_headers(actor_id, "AppealReviewer")


__all__ = [
    "TEST_USERS",
    "make_resident_headers",
    "make_system_operator_headers",
    "make_community_admin_headers",
    "make_appeal_reviewer_headers",
]
