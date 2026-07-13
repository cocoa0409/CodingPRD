"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (Coordinator, IncidentCommander,
# FinanceOfficer), and for Member tests that never exercise ownership.
TEST_USERS = {
    "coordinator_headers": build_user_headers("coord-op-1", "Coordinator"),
    "incident_commander_headers": build_user_headers("ic-op-1", "IncidentCommander"),
    "finance_officer_headers": build_user_headers("fin-op-1", "FinanceOfficer"),
    # Member is entity_backed: this shared constant is a fallback for
    # non-ownership Member calls only (e.g. plain GETs).
    "member_headers": build_user_headers("member-generic-1", "Member"),
}


def make_member_headers(user_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the actual Member.id as
    user_id whenever the call is ownership-gated (acknowledge/decline a callout,
    submit a claim, log a ground track)."""
    return build_user_headers(user_id, "Member")
