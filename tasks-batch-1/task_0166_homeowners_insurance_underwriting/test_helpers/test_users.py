"""Pre-built role headers for every role in the PRD.

Per PRD §2.1:
  - Admin and Agent carry an OPAQUE X-User-ID (not tied to a persisted entity);
    the shared constant is the canonical form.
  - Underwriter and Inspector are ENTITY-BACKED: X-User-ID must equal the acting
    Underwriter.id / Inspector.id. Ownership / resolution checks compare against
    the entity's id, so ownership-gated calls MUST use the per-instance builder
    with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise
# entity-backed ownership / identity resolution.
TEST_USERS = {
    # opaque roles: shared constant is the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    "agent_headers": build_user_headers("test-agent-1", "Agent"),
    # entity_backed roles: shared constant is a fallback for non-ownership tests
    # (e.g. 403-on-role, 400-on-bad-payload). Ownership-gated calls use the
    # builders below with the real entity id.
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
}


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """For Admin (opaque identity). Any operator id is accepted."""
    return build_user_headers(user_id, "Admin")


def make_agent_headers(user_id: str = "test-agent-1") -> dict:
    """For Agent (opaque identity). The id is stamped as agent_id but never resolved."""
    return build_user_headers(user_id, "Agent")


def make_underwriter_headers(user_id: str) -> dict:
    """For Underwriter (entity_backed:Underwriter). Pass the real Underwriter.id
    as user_id whenever the call is ownership/assignment-gated (take-review, bind,
    decline, return-to-queue, lapse, cancel, remove)."""
    return build_user_headers(user_id, "Underwriter")


def make_inspector_headers(user_id: str) -> dict:
    """For Inspector (entity_backed:Inspector). Pass the real Inspector.id as
    user_id whenever the call is identity-resolved (complete, reschedule)."""
    return build_user_headers(user_id, "Inspector")
