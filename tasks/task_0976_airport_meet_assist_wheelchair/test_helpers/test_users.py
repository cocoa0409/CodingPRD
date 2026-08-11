"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. For entity_backed roles (Agent), use make_agent_headers(agent_id)
# whenever the call is ownership-gated.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    "requester_headers": build_user_headers("requester-1", "Requester"),
    "dispatcher_headers": build_user_headers("dispatcher-1", "Dispatcher"),
    "confirmer_headers": build_user_headers("confirmer-1", "Confirmer"),
    "ops_manager_headers": build_user_headers("ops-manager-1", "OpsManager"),
    "billing_clerk_headers": build_user_headers("clerk-1", "BillingClerk"),
    # Fallback for non-ownership contexts only; ownership-gated calls MUST
    # use make_agent_headers(agent["id"]).
    "agent_headers": build_user_headers("test-agent-1", "Agent"),
}


def make_agent_headers(user_id: str) -> dict:
    """Agent role is entity_backed:Agent — X-User-ID must equal the Agent.id
    whenever the call is ownership-gated (assignment lifecycle, tracking)."""
    return build_user_headers(user_id, "Agent")


def make_dispatcher_headers(user_id: str) -> dict:
    """Dispatcher role is opaque — but segregation-of-duties checks compare
    assigned_by_user_id to the acting user id on COMPLETE, so tests that
    need a distinct dispatcher pass a chosen user_id here."""
    return build_user_headers(user_id, "Dispatcher")


def make_confirmer_headers(user_id: str) -> dict:
    """Confirmer role is opaque — pick a user_id distinct from the dispatcher's
    to pass the segregation-of-duties guard on COMPLETE."""
    return build_user_headers(user_id, "Confirmer")


def make_billing_clerk_headers(user_id: str) -> dict:
    """BillingClerk role is opaque — pick distinct user ids when the test
    exercises the airline-write-off segregation-of-duties rule."""
    return build_user_headers(user_id, "BillingClerk")


def make_requester_headers(user_id: str) -> dict:
    """Requester role is opaque."""
    return build_user_headers(user_id, "Requester")
