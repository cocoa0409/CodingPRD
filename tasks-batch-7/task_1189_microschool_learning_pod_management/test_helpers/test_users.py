"""Pre-built role headers for every role in the PRD (PRD 2.1).

Shared constants are used for roles whose X-User-ID is opaque
(PlatformAdmin, PodOperator, ComplianceOfficer, Registrar) and for tests
that do not exercise ownership. Entity-backed roles (Guide, Family) MUST be
built per-instance with make_guide_headers / make_family_headers whenever
the call is ownership- or identity-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "pod_operator_headers": build_user_headers("test-pod-operator-1", "PodOperator"),
    "compliance_officer_headers": build_user_headers(
        "test-compliance-officer-1", "ComplianceOfficer"
    ),
    "registrar_headers": build_user_headers("test-registrar-1", "Registrar"),
    # Entity-backed roles: fallback constants only for non-ownership tests.
    "guide_headers": build_user_headers("test-guide-1", "Guide"),
    "family_headers": build_user_headers("test-family-1", "Family"),
}


def make_guide_headers(user_id: str) -> dict:
    """For Guide (entity-backed). Pass the actual Guide.id as user_id
    whenever the call is ownership- or identity-gated."""
    return build_user_headers(user_id, "Guide")


def make_family_headers(user_id: str) -> dict:
    """For Family (entity-backed). Pass the actual Family.id as user_id
    whenever the call is ownership- or identity-gated."""
    return build_user_headers(user_id, "Family")


def make_registrar_headers(user_id: str) -> dict:
    """Registrar with a specific opaque X-User-ID (used by segregation-of-
    duties tests that must control the filer/reviewer identity)."""
    return build_user_headers(user_id, "Registrar")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
