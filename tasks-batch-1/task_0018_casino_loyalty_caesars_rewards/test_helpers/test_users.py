"""Pre-built role headers for every role in the PRD.

Per PRD §2.1:
  - `Member` identity is entity_backed:Member — X-User-ID must equal the
    acting Member row's `id`. Use `make_member_headers(member_id)`.
  - `MemberServices`, `LoyaltyManager`, `ComplianceOfficer` are opaque
    operator identifiers, not tied to any persisted entity row.

Shared constants under `TEST_USERS` are safe for opaque roles and for
non-ownership tests. For ownership-gated calls on Member, use the
per-instance builder below — falling back to the shared Member constant
would mean X-User-ID never equals any real Member.id and every
ownership check would reject every request.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, plus a Member fallback for
# non-ownership tests.
TEST_USERS = {
    "member_services_headers": build_user_headers("ms_1", "MemberServices"),
    "loyalty_manager_headers": build_user_headers("lm_1", "LoyaltyManager"),
    "loyalty_manager_alice_headers": build_user_headers(
        "lm_alice", "LoyaltyManager",
    ),
    "loyalty_manager_bob_headers": build_user_headers(
        "lm_bob", "LoyaltyManager",
    ),
    "compliance_officer_headers": build_user_headers("co_1", "ComplianceOfficer"),
    # Shared fallback for non-ownership Member tests; ownership-gated calls
    # must use make_member_headers(member_id).
    "member_headers": build_user_headers("test-member-fallback", "Member"),
}


# Per-instance builders ─────────────────────────────────────────────────

def make_member_services_headers(opaque_id: str = "ms_1") -> dict:
    """For MemberServices role (identity: opaque)."""
    return build_user_headers(opaque_id, "MemberServices")


def make_loyalty_manager_headers(opaque_id: str = "lm_1") -> dict:
    """For LoyaltyManager role (identity: opaque)."""
    return build_user_headers(opaque_id, "LoyaltyManager")


def make_compliance_officer_headers(opaque_id: str = "co_1") -> dict:
    """For ComplianceOfficer role (identity: opaque)."""
    return build_user_headers(opaque_id, "ComplianceOfficer")


def make_member_headers(member_id: str) -> dict:
    """For Member role (entity_backed:Member). Pass the actual Member.id as
    user_id whenever the call is ownership-gated. See PRD §2.1."""
    return build_user_headers(member_id, "Member")
