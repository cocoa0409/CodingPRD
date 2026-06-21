"""Pre-built role headers for every role in the PRD.

PolicyHolder is entity_backed:Account — its X-User-ID must equal the owning
Account.id for ownership-gated calls (PRD 2.1). Use make_policy_holder_headers(account_id).
Underwriter and ClaimsAdjuster are opaque operator identifiers (recorded, never
compared to an entity id), so shared constants are the canonical form for them.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # PolicyHolder: shared constant is a fallback for non-ownership tests only
    # (e.g. 401/403-role/404 checks). Ownership-gated calls MUST use the builder.
    "policy_holder_headers": build_user_headers("test-policyholder-1", "PolicyHolder"),
    # opaque roles: shared constant is canonical.
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "claims_adjuster_headers": build_user_headers("test-adjuster-1", "ClaimsAdjuster"),
}


def make_policy_holder_headers(account_id: str) -> dict:
    """For PolicyHolder (entity_backed:Account). Pass the owning Account.id so
    ownership checks (X-User-ID == account chain) pass."""
    return build_user_headers(account_id, "PolicyHolder")


def make_underwriter_headers(user_id: str = "test-underwriter-1") -> dict:
    return build_user_headers(user_id, "Underwriter")


def make_claims_adjuster_headers(user_id: str = "test-adjuster-1") -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")
