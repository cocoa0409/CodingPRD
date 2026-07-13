"""Pre-built role headers for every role in the PRD (§2.1).

The two administrative roles (CaseWorker, ProgramAdmin) are identity-opaque:
their X-User-ID is never compared to a persisted entity, so a shared constant is
always safe.  The two participant roles (Family, Provider) are entity-backed:
ownership checks compare X-User-ID to the resource's family_id / provider_id, so
ownership-gated calls MUST use the per-instance builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for non-ownership tests.
TEST_USERS = {
    "caseworker_headers": build_user_headers("test-caseworker-1", "CaseWorker"),
    "program_admin_headers": build_user_headers("test-programadmin-1", "ProgramAdmin"),
    # Entity-backed fallbacks: only for tests that do NOT exercise ownership
    # (e.g. 401 with headers omitted, or 403 authorization checks).
    "family_headers": build_user_headers("test-family-unknown", "Family"),
    "provider_headers": build_user_headers("test-provider-unknown", "Provider"),
}


# Per-instance builders — required for every entity-backed role.
def make_family_headers(user_id: str) -> dict:
    """For Family (entity_backed:Family). Pass the actual Family.id whenever the
    call is ownership-gated."""
    return build_user_headers(user_id, "Family")


def make_provider_headers(user_id: str) -> dict:
    """For Provider (entity_backed:Provider). Pass the actual Provider.id whenever
    the call is ownership-gated (e.g. submitting/resubmitting attendance)."""
    return build_user_headers(user_id, "Provider")


def make_caseworker_headers(user_id: str = "test-caseworker-1") -> dict:
    return build_user_headers(user_id, "CaseWorker")


def make_program_admin_headers(user_id: str = "test-programadmin-1") -> dict:
    return build_user_headers(user_id, "ProgramAdmin")
