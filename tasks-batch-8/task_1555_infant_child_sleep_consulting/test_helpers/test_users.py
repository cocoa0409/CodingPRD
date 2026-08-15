"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (Anonymous, PracticeAdmin) and for
# tests whose outcome does not depend on the caller owning the subject resource.
TEST_USERS = {
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    "practice_admin_headers": build_user_headers("test-admin-1", "PracticeAdmin"),
    # Fallbacks for entity-backed roles: use ONLY for non-ownership probes
    # (e.g., malformed-payload or not-found tests). Ownership-gated calls must
    # use the per-instance builders below with the real entity id.
    "parent_headers": build_user_headers("test-parent-1", "Parent"),
    "consultant_headers": build_user_headers("test-consultant-1", "Consultant"),
}


def make_parent_headers(family_id: str) -> dict:
    """Parent is entity-backed by ClientFamily: X-User-ID must be the family's id
    whenever the call is ownership-gated."""
    return build_user_headers(family_id, "Parent")


def make_consultant_headers(consultant_id: str) -> dict:
    """Consultant is entity-backed by Consultant: X-User-ID must be the
    consultant's id whenever the call is an assignment-gated clinical action."""
    return build_user_headers(consultant_id, "Consultant")
