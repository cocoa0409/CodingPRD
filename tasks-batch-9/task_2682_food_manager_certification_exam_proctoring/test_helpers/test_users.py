"""Pre-built role headers for every role in the PRD.

Every request must carry both X-User-ID and X-User-Role (PRD 2.1).
PlatformAdmin's X-User-ID is an opaque operator identifier; the other four
roles carry the id of the entity they act as, so ownership-gated calls MUST
use the matching per-instance builder below.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the opaque PlatformAdmin role, and for tests that
# do not exercise resource ownership at all.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-ops-1", "PlatformAdmin"),
    "platform_admin_alt_headers": build_user_headers("admin-ops-2", "PlatformAdmin"),
    "scoring_admin_headers": build_user_headers("admin-scoring-1", "PlatformAdmin"),
    "security_admin_headers": build_user_headers("admin-security-1", "PlatformAdmin"),
    "provider_admin_headers": build_user_headers("test-provider-1", "ProviderAdmin"),
    "proctor_headers": build_user_headers("test-proctor-1", "Proctor"),
    "candidate_headers": build_user_headers("test-candidate-1", "Candidate"),
    "health_officer_headers": build_user_headers("test-jurisdiction-1", "HealthOfficer"),
}


def make_platform_admin_headers(user_id: str = "admin-ops-1") -> dict:
    """PlatformAdmin's X-User-ID is opaque and never compared to an entity id."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_provider_admin_headers(training_provider_id: str) -> dict:
    """Pass the acting TrainingProvider's own id."""
    return build_user_headers(training_provider_id, "ProviderAdmin")


def make_proctor_headers(proctor_id: str) -> dict:
    """Pass the acting Proctor's own id."""
    return build_user_headers(proctor_id, "Proctor")


def make_candidate_headers(candidate_id: str) -> dict:
    """Pass the acting Candidate's own id."""
    return build_user_headers(candidate_id, "Candidate")


def make_health_officer_headers(jurisdiction_id: str) -> dict:
    """Pass the acting Jurisdiction's own id."""
    return build_user_headers(jurisdiction_id, "HealthOfficer")
