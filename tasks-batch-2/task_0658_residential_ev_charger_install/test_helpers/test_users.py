"""Pre-built role headers for every role in the PRD.

Homeowner and Electrician are entity-backed: ownership checks compare X-User-ID
to a real entity id. Tests/fixtures that exercise ownership MUST use the per-instance
builders (make_homeowner_headers / make_electrician_headers) with the actual entity id.
The shared TEST_USERS constants are only safe for opaque roles (Coordinator,
UtilityReviewer, Anonymous) and for non-ownership tests (bad payload, missing resource,
forbidden-role, unauthenticated).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constant is the canonical form.
    "coordinator_headers": build_user_headers("test-coordinator-1", "Coordinator"),
    "utility_reviewer_headers": build_user_headers("test-utility-1", "UtilityReviewer"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # Entity-backed roles — shared constant is a fallback for non-ownership tests only.
    "homeowner_headers": build_user_headers("test-homeowner-1", "Homeowner"),
    "electrician_headers": build_user_headers("test-electrician-1", "Electrician"),
}


def make_homeowner_headers(user_id: str) -> dict:
    """For Homeowner (entity_backed:Homeowner). Pass the actual Homeowner.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Homeowner")


def make_electrician_headers(user_id: str) -> dict:
    """For Electrician (entity_backed:Electrician). Pass the actual Electrician.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Electrician")


def make_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    return build_user_headers(user_id, "Coordinator")


def make_utility_reviewer_headers(user_id: str = "test-utility-1") -> dict:
    return build_user_headers(user_id, "UtilityReviewer")


def make_anonymous_headers(user_id: str = "test-anon-1") -> dict:
    return build_user_headers(user_id, "Anonymous")
