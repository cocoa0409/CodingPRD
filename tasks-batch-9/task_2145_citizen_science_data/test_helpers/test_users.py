"""Pre-built role headers for every role in the PRD.

`ProgramAdmin` is opaque: its `X-User-ID` is an operator identifier that is
never compared to any row, so the shared constant is the canonical form.
`Volunteer`, `Expert` and `ResearchPartner` are entity-backed: their
`X-User-ID` must be the `id` of a live row, so callers MUST use the
per-instance builders below with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role - the shared constant is correct everywhere.
    "program_admin_headers": build_user_headers("ops-admin-1", "ProgramAdmin"),
    # Entity-backed roles - shared constants are ONLY safe for tests that
    # never reach an actor-existence or ownership check.
    "volunteer_headers": build_user_headers("test-volunteer-1", "Volunteer"),
    "expert_headers": build_user_headers("test-expert-1", "Expert"),
    "research_partner_headers": build_user_headers("test-partner-1", "ResearchPartner"),
}

ADMIN = TEST_USERS["program_admin_headers"]


def make_program_admin_headers(user_id: str = "ops-admin-1") -> dict:
    """ProgramAdmin is opaque; any operator identifier is acceptable."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_volunteer_headers(user_id: str) -> dict:
    """Pass the acting Volunteer's own `id` as `user_id`."""
    return build_user_headers(user_id, "Volunteer")


def make_expert_headers(user_id: str) -> dict:
    """Pass the acting Expert's own `id` as `user_id`."""
    return build_user_headers(user_id, "Expert")


def make_research_partner_headers(user_id: str) -> dict:
    """Pass the acting ResearchPartner's own `id` as `user_id`."""
    return build_user_headers(user_id, "ResearchPartner")


def make_headers(user_id: str, role: str) -> dict:
    """Free-form builder for role-matrix tests."""
    return build_user_headers(user_id, role)


NO_AUTH_HEADERS = {"Content-Type": "application/json"}
