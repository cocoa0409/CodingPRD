"""Pre-built role headers for every role in the PRD (§2.1).

ReferringProvider and SpecialistProvider are entity-backed: their X-User-ID must
be the acting entity's id. Use the make_* builders with the real entity id for
any ownership-gated call; the shared constants are fallbacks for tests that do
not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared constants.
    "network_admin_headers": build_user_headers("admin-1", "NetworkAdmin"),
    "coordinator_headers": build_user_headers("coord-1", "ReferralCoordinator"),
    "coordinator_alt_headers": build_user_headers("coord-2", "ReferralCoordinator"),
    "auditor_headers": build_user_headers("audit-1", "ComplianceAuditor"),
    # Entity-backed roles — fallback constants for non-ownership tests only.
    "referring_provider_headers": build_user_headers("test-referring-provider-1", "ReferringProvider"),
    "specialist_provider_headers": build_user_headers("test-specialist-provider-1", "SpecialistProvider"),
}


def make_referring_provider_headers(provider_id: str) -> dict:
    """Headers for the entity-backed ReferringProvider role.

    Pass the actual ReferringProvider.id whenever the call is ownership-gated
    (referral creation, resubmit, provider-scoped reads).
    """
    return build_user_headers(provider_id, "ReferringProvider")


def make_specialist_provider_headers(specialist_id: str) -> dict:
    """Headers for the entity-backed SpecialistProvider role.

    Pass the actual SpecialistProvider.id whenever the call is ownership-gated
    (appointment complete, consult note).
    """
    return build_user_headers(specialist_id, "SpecialistProvider")


def make_coordinator_headers(user_id: str) -> dict:
    """Headers for an opaque ReferralCoordinator operator id."""
    return build_user_headers(user_id, "ReferralCoordinator")


def make_auditor_headers(user_id: str) -> dict:
    """Headers for an opaque ComplianceAuditor operator id."""
    return build_user_headers(user_id, "ComplianceAuditor")
