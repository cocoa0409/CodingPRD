"""Pre-built role headers for every role in the PRD (§2.1).

Administrator and RoyaltyOperator are operator identities: X-User-ID is an opaque
operator identifier not tied to any persisted entity. The shared constants below
are the canonical form for those two roles.

Licensee and Rightsholder are entity-backed: X-User-ID is the acting Rightsholder.id.
For ownership-gated calls, use the per-instance builders make_licensee_headers /
make_rightsholder_headers with the actual Rightsholder.id — the shared constants are
fallbacks only for non-ownership tests (e.g. RBAC 403 on an operator-exclusive route).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator identities — shared constant is the canonical form.
    "administrator_headers": build_user_headers("test-admin-1", "Administrator"),
    "operator_headers": build_user_headers("test-operator-1", "RoyaltyOperator"),
    # Entity-backed roles — shared constant is a fallback for non-ownership tests only.
    "licensee_headers": build_user_headers("test-licensee-1", "Licensee"),
    "rightsholder_headers": build_user_headers("test-rightsholder-1", "Rightsholder"),
}


def make_administrator_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "Administrator")


def make_operator_headers(user_id: str = "test-operator-1") -> dict:
    return build_user_headers(user_id, "RoyaltyOperator")


def make_licensee_headers(user_id: str) -> dict:
    """For Licensee (entity_backed:Rightsholder). Pass the acting Rightsholder.id
    (the SyncLicense.licensee_id) whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Licensee")


def make_rightsholder_headers(user_id: str) -> dict:
    """For Rightsholder (entity_backed:Rightsholder). Pass the acting Rightsholder.id
    whenever the read is ownership-gated."""
    return build_user_headers(user_id, "Rightsholder")
