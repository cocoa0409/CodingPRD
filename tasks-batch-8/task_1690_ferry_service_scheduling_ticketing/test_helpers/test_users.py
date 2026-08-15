"""Pre-built role headers for every role in the PRD (§2.1).

SchedulerAdmin, TerminalAgent, and CrewPlanner are opaque roles: their
X-User-ID is never compared to any entity id, so the shared constants are
canonical. Customer is entity-backed: X-User-ID must be the acting Customer
record's id for any ownership-gated call, so use make_customer_headers with
the real customer id there; the shared constant is a fallback only for tests
that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "scheduler_admin_headers": build_user_headers("test-scheduler-admin-1", "SchedulerAdmin"),
    "terminal_agent_headers": build_user_headers("test-terminal-agent-1", "TerminalAgent"),
    "crew_planner_headers": build_user_headers("test-crew-planner-1", "CrewPlanner"),
    # Entity-backed role: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity-backed). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated (booking confirm/modify/cancel/rebook,
    standby join/leave)."""
    return build_user_headers(user_id, "Customer")
