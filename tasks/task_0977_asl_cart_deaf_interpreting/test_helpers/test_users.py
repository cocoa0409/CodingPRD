"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque roles: shared constant is the canonical form
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "quality_reviewer_headers": build_user_headers("test-reviewer-1", "QualityReviewer"),
    "billing_clerk_headers": build_user_headers("test-clerk-1", "BillingClerk"),
    # entity_backed roles: fallback only for non-ownership-gated calls
    # (e.g. 400-on-bad-payload before ownership is reached, or reads as Any).
    "org_requester_headers": build_user_headers("test-org-fallback-1", "OrgRequester"),
    "interpreter_headers": build_user_headers("test-interp-fallback-1", "Interpreter"),
}


# Per-instance builders — required for the entity_backed roles.
def make_org_requester_headers(user_id: str) -> dict:
    """OrgRequester is entity_backed by RequestingOrg: pass the actual org id
    whenever the call is ownership-gated (submit/cancel/verify/dispute/complaint)."""
    return build_user_headers(user_id, "OrgRequester")


def make_interpreter_headers(user_id: str) -> dict:
    """Interpreter is entity_backed by Interpreter: pass the actual interpreter id
    whenever the call is ownership-gated (accept/decline/depart/check-in/check-out,
    availability, self-scoped certifications)."""
    return build_user_headers(user_id, "Interpreter")
