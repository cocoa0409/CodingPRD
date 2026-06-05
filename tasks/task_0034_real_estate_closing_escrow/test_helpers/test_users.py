"""Pre-built role headers for every role in the PRD (PRD §2.1).

All three roles (`EscrowOfficer`, `TitleAgent`, `ComplianceOfficer`) are
entity-backed (PRD §2.1): `X-User-ID` for any of them must equal the `id`
of an actual `User` row created via `POST /users`. Ownership checks
(`escrow_officer_id` on `EscrowAccount`, `callback_verifier_id` on
`WireInstruction`, segregation-of-duties checks at wire lock) compare
those FK fields against `X-User-ID`.

The shared `TEST_USERS` constants carry placeholder X-User-IDs. They are
safe ONLY for tests that don't exercise ownership (e.g., 401-on-no-role,
403-on-wrong-role, raw 400/404 paths). For any test that needs the call
to succeed in the entity-backed sense, the caller MUST use
`make_<role>_headers(user["id"])` after creating the User via `create_user`.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Shared constants — placeholder X-User-IDs. Safe for negative-path
    # tests where ownership is not exercised; entity-backed positive
    # paths must use the per-instance builders below.
    "escrow_officer_headers": build_user_headers("test-escrow-officer-1", "EscrowOfficer"),
    "title_agent_headers": build_user_headers("test-title-agent-1", "TitleAgent"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
}


def make_escrow_officer_headers(user_id: str) -> dict:
    """Headers for an EscrowOfficer bound to a specific User.id (PRD §2.1)."""
    return build_user_headers(user_id, "EscrowOfficer")


def make_title_agent_headers(user_id: str) -> dict:
    """Headers for a TitleAgent bound to a specific User.id (PRD §2.1)."""
    return build_user_headers(user_id, "TitleAgent")


def make_compliance_officer_headers(user_id: str) -> dict:
    """Headers for a ComplianceOfficer bound to a specific User.id (PRD §2.1)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_headers(user_id: str, role: str) -> dict:
    """Generic constructor for parametrized RBAC tests."""
    return build_user_headers(user_id, role)
