"""Pre-built role headers for every request role in the PRD (§2.1).

TeamAdmin is opaque: its X-User-ID is never compared to any entity id, so the
shared constant is canonical. TeamLeader / Agent / ReferralPartner are
entity-backed: ownership-gated calls MUST use the per-instance builders below
with the actual entity's id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role: canonical shared form.
    "team_admin_headers": build_user_headers("test-admin-1", "TeamAdmin"),
    # Entity-backed roles: shared constants only for tests that do NOT depend
    # on the caller owning the subject resource (e.g. 400/404 checks).
    "team_leader_headers": build_user_headers("test-leader-1", "TeamLeader"),
    "agent_headers": build_user_headers("test-agent-1", "Agent"),
    "referral_partner_headers": build_user_headers("test-partner-1", "ReferralPartner"),
}


def make_team_admin_headers(user_id: str = "test-admin-1") -> dict:
    """TeamAdmin (opaque identity)."""
    return build_user_headers(user_id, "TeamAdmin")


def make_team_leader_headers(user_id: str) -> dict:
    """TeamLeader — pass the id of an Agent whose role_on_team is LEADER."""
    return build_user_headers(user_id, "TeamLeader")


def make_agent_headers(user_id: str) -> dict:
    """Agent — pass the acting Agent's id for ownership-gated calls."""
    return build_user_headers(user_id, "Agent")


def make_referral_partner_headers(user_id: str) -> dict:
    """ReferralPartner — pass the acting ReferralPartner's id."""
    return build_user_headers(user_id, "ReferralPartner")
