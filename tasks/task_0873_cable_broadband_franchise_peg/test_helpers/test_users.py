"""Pre-built role headers for every role in the PRD.

- FranchiseAuthority and Resident are opaque identities: X-User-ID is not tied
  to any persisted entity.
- Operator is entity_backed:Franchise: X-User-ID must equal the id of the
  Franchise the operator holds. Ownership checks compare the resource's
  franchise_id to X-User-ID, so ownership-gated Operator calls MUST use
  make_operator_headers(franchise_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that never exercise
# Operator ownership.
TEST_USERS = {
    "authority_headers": build_user_headers("authority-1", "FranchiseAuthority"),
    "resident_headers": build_user_headers("res-1", "Resident"),
    # Operator fallback — only valid where ownership is not enforced.
    "operator_headers": build_user_headers("operator-unowned", "Operator"),
}


def make_authority_headers(user_id: str = "authority-1") -> dict:
    """FranchiseAuthority headers with a specific opaque X-User-ID.

    Used to distinguish the audit-finalizing issuer (e.g. "authority-lead")
    from a different waiving authority for segregation-of-duties tests.
    """
    return build_user_headers(user_id, "FranchiseAuthority")


def make_operator_headers(franchise_id: str) -> dict:
    """Operator headers whose X-User-ID equals the owned Franchise.id.

    Mandatory for every ownership-gated Operator write against a
    franchise-scoped resource.
    """
    return build_user_headers(franchise_id, "Operator")


def make_resident_headers(user_id: str) -> dict:
    """Resident headers with a specific opaque X-User-ID (stored as complainant_id)."""
    return build_user_headers(user_id, "Resident")


def anonymous_headers() -> dict:
    """Headers with NO X-User-Role, for unauthenticated-request tests."""
    return {"X-User-ID": "anon", "Content-Type": "application/json"}
