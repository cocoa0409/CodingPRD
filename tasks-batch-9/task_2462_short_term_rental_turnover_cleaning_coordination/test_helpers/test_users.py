"""Pre-built role headers for every role in the PRD (§2.1).

Three roles carry an opaque operator identifier in `X-User-ID`
(`PlatformAdmin`, `Coordinator`, `QualityAuditor`), so the shared constants
below are the canonical form for them. Two roles are entity-backed: a
`Cleaner` sends the acting `Cleaner` record's `id` and a `PropertyOwner`
sends the acting `Property` record's `id`. Ownership-gated calls for those
two roles MUST use the per-instance builders, passing the real entity id.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Distinct operator identities. Segregation of duties is keyed on X-User-ID,
# so the coordinator who offers work, the coordinator who reviews evidence and
# the auditor who samples must be able to differ.
ADMIN_USER_ID = "admin-1"
COORDINATOR_ASSIGN_USER_ID = "coord-1"
COORDINATOR_REVIEW_USER_ID = "coord-2"
COORDINATOR_THIRD_USER_ID = "coord-3"
COORDINATOR_FOURTH_USER_ID = "coord-4"
AUDITOR_USER_ID = "auditor-1"
AUDITOR_SECOND_USER_ID = "auditor-2"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque operator identities — the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    "coordinator_headers": build_user_headers(COORDINATOR_ASSIGN_USER_ID, "Coordinator"),
    "coordinator_reviewer_headers": build_user_headers(
        COORDINATOR_REVIEW_USER_ID, "Coordinator"),
    "coordinator_third_headers": build_user_headers(
        COORDINATOR_THIRD_USER_ID, "Coordinator"),
    "coordinator_fourth_headers": build_user_headers(
        COORDINATOR_FOURTH_USER_ID, "Coordinator"),
    "quality_auditor_headers": build_user_headers(AUDITOR_USER_ID, "QualityAuditor"),
    "quality_auditor_second_headers": build_user_headers(
        AUDITOR_SECOND_USER_ID, "QualityAuditor"),
    # Entity-backed roles — these fallbacks are for tests that never reach an
    # ownership check (a 401/403/400/404 probe). Ownership-gated calls must use
    # make_cleaner_headers() / make_property_owner_headers() instead.
    "cleaner_headers": build_user_headers("cleaner-x", "Cleaner"),
    "property_owner_headers": build_user_headers("owner-x", "PropertyOwner"),
}


def make_cleaner_headers(cleaner_id: str) -> Dict[str, str]:
    """Headers for the acting Cleaner. `X-User-ID` is the Cleaner record's id."""
    return build_user_headers(cleaner_id, "Cleaner")


def make_property_owner_headers(property_id: str) -> Dict[str, str]:
    """Headers for the acting PropertyOwner. `X-User-ID` is the Property's id."""
    return build_user_headers(property_id, "PropertyOwner")


def make_coordinator_headers(user_id: str) -> Dict[str, str]:
    """Headers for a specific Coordinator operator identity."""
    return build_user_headers(user_id, "Coordinator")


def make_quality_auditor_headers(user_id: str) -> Dict[str, str]:
    """Headers for a specific QualityAuditor operator identity."""
    return build_user_headers(user_id, "QualityAuditor")


def make_platform_admin_headers(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """Headers for a specific PlatformAdmin operator identity."""
    return build_user_headers(user_id, "PlatformAdmin")
