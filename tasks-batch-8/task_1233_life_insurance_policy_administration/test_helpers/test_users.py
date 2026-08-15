"""Pre-built role headers for every role in the PRD (§2.1).

Agent and Policyholder are entity-backed roles: their X-User-ID is the id of
the acting InsuredPerson, and ownership checks compare a resource's
insured-person reference to X-User-ID. Use make_agent_headers /
make_policyholder_headers with the real InsuredPerson id whenever the call is
ownership-gated (e.g. loans, non-forfeiture elections, dividend option).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles: shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "underwriter_u2_headers": build_user_headers("test-underwriter-2", "Underwriter"),
    "policy_issuer_headers": build_user_headers("test-policy-issuer-1", "PolicyIssuer"),
    # Entity-backed roles: shared constants are a fallback for tests that do
    # not exercise ownership (payload-validation, RBAC, 404 checks).
    "agent_headers": build_user_headers("test-agent-1", "Agent"),
    "policyholder_headers": build_user_headers("test-policyholder-1", "Policyholder"),
}


def make_agent_headers(user_id: str) -> dict:
    """Agent is entity-backed by InsuredPerson. Pass the real InsuredPerson.id
    whenever the downstream call is ownership-gated."""
    return build_user_headers(user_id, "Agent")


def make_policyholder_headers(user_id: str) -> dict:
    """Policyholder is entity-backed by InsuredPerson. Pass the policy's
    insured_person_id whenever the call is ownership-gated (loans,
    repayments, non-forfeiture elections, dividend option)."""
    return build_user_headers(user_id, "Policyholder")


def make_underwriter_headers(user_id: str) -> dict:
    """Underwriter is an opaque operator role; the id is recorded for audit
    and segregation-of-duties checks only."""
    return build_user_headers(user_id, "Underwriter")


def make_policy_issuer_headers(user_id: str) -> dict:
    """PolicyIssuer is an opaque operator role; the id must differ from the
    approving underwriter's id at issuance (PRD §2.11)."""
    return build_user_headers(user_id, "PolicyIssuer")


def make_platform_admin_headers(user_id: str) -> dict:
    """PlatformAdmin is an opaque operator role."""
    return build_user_headers(user_id, "PlatformAdmin")
