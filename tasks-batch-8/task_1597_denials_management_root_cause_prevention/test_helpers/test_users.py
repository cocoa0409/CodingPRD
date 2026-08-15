"""Pre-built role headers for the five roles named in PRD §2.1.

All five roles are opaque operator identities (PRD §2.1: "`X-User-ID` is an
opaque operator identifier not tied to any persisted entity"), so the shared
constants below are the canonical form. Tests that exercise
segregation-of-duties comparisons (PRD §2.8 gate 9) build per-user headers
with build_user_headers("<user-id>", "<Role>") directly.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "specialist_headers": build_user_headers("spec-default", "DenialsSpecialist"),
    "manager_headers": build_user_headers("mgr-default", "DenialsManager"),
    "director_headers": build_user_headers("dir-default", "RevenueCycleDirector"),
    "upstream_owner_headers": build_user_headers("uo-default", "UpstreamOwner"),
    "auditor_headers": build_user_headers("aud-default", "ComplianceAuditor"),
}


def specialist_headers(user_id: str) -> dict:
    """DenialsSpecialist headers for a specific operator id (SoD scenarios)."""
    return build_user_headers(user_id, "DenialsSpecialist")


def manager_headers(user_id: str) -> dict:
    """DenialsManager headers for a specific operator id (SoD scenarios)."""
    return build_user_headers(user_id, "DenialsManager")


def director_headers(user_id: str) -> dict:
    """RevenueCycleDirector headers for a specific operator id."""
    return build_user_headers(user_id, "RevenueCycleDirector")


def upstream_owner_headers(user_id: str) -> dict:
    """UpstreamOwner headers for a specific operator id (implementer vs verifier)."""
    return build_user_headers(user_id, "UpstreamOwner")


def auditor_headers(user_id: str) -> dict:
    """ComplianceAuditor headers for a specific operator id."""
    return build_user_headers(user_id, "ComplianceAuditor")
