"""Pre-built role headers for every role in the PRD (§2.1).

Roles: Anonymous, Trader (entity_backed:Account), Operator (opaque),
ComplianceOfficer (opaque).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise
# Trader ownership (404/422-on-bad-payload, or Operator/ComplianceOfficer calls).
TEST_USERS = {
    # Trader is entity_backed:Account; the shared constant is a fallback only for
    # non-ownership tests. Ownership-gated Trader calls MUST use make_trader_headers().
    "trader_headers": build_user_headers("test-trader-1", "Trader"),
    "operator_headers": build_user_headers("test-operator-1", "Operator"),
    "compliance_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "compliance_headers_2": build_user_headers("test-compliance-2", "ComplianceOfficer"),
    # Anonymous: X-User-ID is opaque; account registration is the only operation.
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
}


# Per-instance builders — required for every entity_backed role.
def make_trader_headers(user_id: str) -> dict:
    """For Trader (entity_backed:Account). Pass the actual Account.id as user_id
    whenever the call is ownership-gated (PRD §2.1: X-User-ID is the acting
    Account's id; ownership checks compare resource.account_id to X-User-ID)."""
    return build_user_headers(user_id, "Trader")


def make_operator_headers(user_id: str = "test-operator-1") -> dict:
    """For Operator (opaque). X-User-ID is not tied to any entity."""
    return build_user_headers(user_id, "Operator")


def make_compliance_headers(user_id: str) -> dict:
    """For ComplianceOfficer (opaque). The screening officer's X-User-ID is
    recorded for the segregation-of-duties check (PRD §2.1, §3.6)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_anonymous_headers(user_id: str = "test-anon-1") -> dict:
    return build_user_headers(user_id, "Anonymous")


def make_headers(role: str, user_id: str) -> dict:
    """Generic builder for tests that need an arbitrary (possibly unknown) role,
    e.g. authentication-rejection tests."""
    return build_user_headers(user_id, role)
