"""Pre-built role headers for every role in the PRD (PRD §2.1).

Both roles are operator identities, not client identities (PRD §2.1): when
`X-User-Role` is `Advisor` or `Compliance`, `X-User-ID` is an opaque operator
identifier that is never compared to any entity's `id`. There are therefore no
entity-backed roles here, and the shared constants below are the canonical form
for every call. Ownership of a client account is established by the account's
`client_email` and FK references, never by the acting user header.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constants are canonical (PRD §2.1).
    "advisor_headers": build_user_headers("test-advisor-1", "Advisor"),
    "compliance_headers": build_user_headers("test-compliance-1", "Compliance"),
}


def make_advisor_headers(user_id: str = "test-advisor-1") -> dict:
    """Headers for the opaque Advisor role (PRD §2.1)."""
    return build_user_headers(user_id, "Advisor")


def make_compliance_headers(user_id: str = "test-compliance-1") -> dict:
    """Headers for the opaque Compliance role (PRD §2.1)."""
    return build_user_headers(user_id, "Compliance")


def make_headers(user_id: str, role: str) -> dict:
    """Generic constructor for parametrized RBAC / auth tests."""
    return build_user_headers(user_id, role)
