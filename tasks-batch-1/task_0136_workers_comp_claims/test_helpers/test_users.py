"""Pre-built role headers for every role in the PRD.

Three roles (PlatformAdmin, ClaimsAdjuster, MedicalReviewer) are opaque operator
identities: their X-User-ID is not tied to any persisted entity, so the shared
constant is the canonical form. The Employer role is entity-backed: its X-User-ID
must be the acting Employer entity's id, so ownership-gated calls MUST use the
per-instance builder make_employer_headers(employer_id).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque roles use these directly; the entity-backed Employer
# constant is a fallback only for non-ownership tests (e.g., 401/403/404 paths).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "claims_adjuster_headers": build_user_headers("test-adjuster-1", "ClaimsAdjuster"),
    "medical_reviewer_headers": build_user_headers("test-reviewer-1", "MedicalReviewer"),
    "employer_headers": build_user_headers("test-employer-1", "Employer"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    """PlatformAdmin is opaque; user_id is an arbitrary operator id."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_claims_adjuster_headers(user_id: str) -> dict:
    """ClaimsAdjuster is opaque; user_id is the operator id the server records for
    the separation-of-duties protocol (which adjuster set a claim's reserve)."""
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_medical_reviewer_headers(user_id: str) -> dict:
    """MedicalReviewer is opaque; pass a specific operator id when a test needs the
    same/different identity for separation-of-duties checks."""
    return build_user_headers(user_id, "MedicalReviewer")


def make_employer_headers(user_id: str) -> dict:
    """Employer is entity_backed:Employer. Pass the acting Employer entity's id as
    user_id whenever the call is ownership-gated (creating workers/claims/RTW offers
    scoped to that employer)."""
    return build_user_headers(user_id, "Employer")
