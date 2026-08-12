"""Pre-built role headers for every role in the PRD.

Entity-backed roles (ReferringProvider, Specialist, QualityReviewer) compare
X-User-ID against a persisted entity id, so ownership-gated calls MUST use the
per-instance builders with the real entity id. Opaque roles (ProgramCoordinator,
BillingClerk) are never compared to entity ids and can use the shared constants.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for non-ownership-gated calls.
TEST_USERS = {
    "coordinator_headers": build_user_headers("test-coordinator-1", "ProgramCoordinator"),
    "billing_headers": build_user_headers("test-billing-1", "BillingClerk"),
    # Fallbacks for non-ownership tests only (400/404/role-gate scenarios).
    "provider_headers": build_user_headers("test-provider-1", "ReferringProvider"),
    "specialist_headers": build_user_headers("test-specialist-1", "Specialist"),
    "reviewer_headers": build_user_headers("test-reviewer-1", "QualityReviewer"),
}


def make_provider_headers(user_id: str) -> dict:
    """ReferringProvider is entity-backed: pass the real ReferringProvider.id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "ReferringProvider")


def make_specialist_headers(user_id: str) -> dict:
    """Specialist is entity-backed: pass the real Specialist.id whenever the
    call is ownership-gated (assigned responses, windows, conversions...)."""
    return build_user_headers(user_id, "Specialist")


def make_reviewer_headers(user_id: str) -> dict:
    """QualityReviewer's X-User-ID is a Specialist id; pass the reviewing
    specialist's real id (it must differ from the responding specialist)."""
    return build_user_headers(user_id, "QualityReviewer")


def make_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    return build_user_headers(user_id, "ProgramCoordinator")


def make_billing_headers(user_id: str = "test-billing-1") -> dict:
    return build_user_headers(user_id, "BillingClerk")
