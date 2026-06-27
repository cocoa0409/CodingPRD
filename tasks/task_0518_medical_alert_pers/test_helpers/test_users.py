"""Pre-built role headers for every role in the PRD.

PlatformAdmin and CallCenterAgent identities are opaque (X-User-ID not tied to any
persisted entity). Subscriber is entity_backed:Subscriber — ownership checks compare a
resource's subscriber_id (directly or transitively) to X-User-ID, so any ownership-gated
Subscriber call MUST use make_subscriber_headers(subscriber_id) with the real Subscriber.id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise ownership.
TEST_USERS = {
    # opaque roles: shared constant is the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "agent_headers": build_user_headers("test-agent-1", "CallCenterAgent"),
    # entity_backed role: shared constant is a fallback for NON-ownership tests only
    # (e.g. forbidden-role checks). Ownership-gated calls must use make_subscriber_headers.
    "subscriber_headers": build_user_headers("test-subscriber-1", "Subscriber"),
}


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """For PlatformAdmin (opaque identity). user_id is an opaque operator id."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_agent_headers(user_id: str) -> dict:
    """For CallCenterAgent (opaque identity). user_id is the agent's opaque operator id,
    which is recorded as AlarmEvent.assigned_agent_id and keyed to AgentShift.agent_user_id."""
    return build_user_headers(user_id, "CallCenterAgent")


def make_subscriber_headers(user_id: str) -> dict:
    """For Subscriber (entity_backed:Subscriber). Pass the actual Subscriber.id as user_id
    whenever the call is ownership-gated (devices/contacts/contracts/holds the subscriber owns)."""
    return build_user_headers(user_id, "Subscriber")
