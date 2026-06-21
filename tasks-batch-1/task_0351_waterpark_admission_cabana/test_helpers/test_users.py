"""Pre-built role headers for every role in the PRD (§2.1).

Four roles: Guest, GateAgent, ParkManager, FinanceClerk.

Guest is the only entity-backed role: a Guest's X-User-ID is the id of the
acting Guest entity, and ownership checks compare a resource's guest_id to
X-User-ID (PRD §2.1). Ownership-gated Guest calls MUST therefore use
make_guest_headers(guest["id"]) with the real Guest id — never the shared
constant, whose string id never equals any persisted Guest.

GateAgent, ParkManager, and FinanceClerk carry opaque X-User-ID values that the
server does not match against any entity (PRD §2.1); the shared constants are
the canonical form for them.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # entity_backed:Guest — shared constant is a fallback for non-ownership tests only
    # (e.g. unauthenticated/forbidden/404 checks that never resolve ownership).
    "guest_headers": build_user_headers("test-guest-1", "Guest"),
    # opaque roles — shared constant is the canonical form.
    "gate_agent_headers": build_user_headers("test-gate-agent-1", "GateAgent"),
    "park_manager_headers": build_user_headers("test-park-manager-1", "ParkManager"),
    "finance_clerk_headers": build_user_headers("test-finance-clerk-1", "FinanceClerk"),
}


def make_guest_headers(user_id: str) -> dict:
    """For the Guest role (entity_backed:Guest). Pass the actual Guest.id as
    user_id whenever the call is ownership-gated (orders/admissions/rentals
    owned by that guest)."""
    return build_user_headers(user_id, "Guest")


def make_gate_agent_headers(user_id: str = "test-gate-agent-1") -> dict:
    return build_user_headers(user_id, "GateAgent")


def make_park_manager_headers(user_id: str = "test-park-manager-1") -> dict:
    return build_user_headers(user_id, "ParkManager")


def make_finance_clerk_headers(user_id: str = "test-finance-clerk-1") -> dict:
    return build_user_headers(user_id, "FinanceClerk")
