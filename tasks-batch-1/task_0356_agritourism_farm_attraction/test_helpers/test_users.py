"""Pre-built role headers for every role in the PRD.

FarmManager and GateAgent are opaque operator identities (PRD §2.1: the server
records but does not match their X-User-ID against any owner field), so the
shared constant is the canonical form. Visitor and GroupLeader are backed by a
Visitor entity — ownership-gated calls MUST use make_visitor_headers(visitor_id)
or make_group_leader_headers(leader_id) with the real Visitor.id, or every
ownership check rejects the request.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   - FarmManager / GateAgent: opaque identity, shared constant is canonical.
#   - Visitor / GroupLeader: shared constant is a fallback for non-ownership
#     tests only (e.g. 401/403/404 paths, or tests that never hit an owner gate).
TEST_USERS = {
    "farm_manager_headers": build_user_headers("manager-1", "FarmManager"),
    "gate_agent_headers": build_user_headers("agent-1", "GateAgent"),
    "visitor_headers": build_user_headers("visitor-1", "Visitor"),
    "group_leader_headers": build_user_headers("leader-1", "GroupLeader"),
}


def make_visitor_headers(visitor_id: str) -> dict:
    """For a Visitor (entity_backed:Visitor). Pass the acting Visitor.id as
    user_id whenever the call is ownership-gated (create/confirm/cancel a
    reservation, attach activity/waiver/pumpkin lines)."""
    return build_user_headers(visitor_id, "Visitor")


def make_group_leader_headers(leader_id: str) -> dict:
    """For a GroupLeader (entity_backed:Visitor). Pass the acting Visitor.id as
    user_id whenever the call is ownership-gated (create/edit/revise/requote/
    confirm/cancel the leader's own GroupBooking)."""
    return build_user_headers(leader_id, "GroupLeader")


def make_farm_manager_headers(user_id: str = "manager-1") -> dict:
    return build_user_headers(user_id, "FarmManager")


def make_gate_agent_headers(user_id: str = "agent-1") -> dict:
    return build_user_headers(user_id, "GateAgent")
