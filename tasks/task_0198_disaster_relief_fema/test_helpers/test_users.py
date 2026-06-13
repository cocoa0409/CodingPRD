"""Pre-built role headers for every role in the PRD (§2.1).

ProgramAdmin is an opaque operator identity — its X-User-ID is recorded but never
compared to any entity id, so the shared constant is the canonical form.

Inspector (entity_backed:Inspector) and Caseworker (entity_backed:Caseworker) must
carry an X-User-ID equal to the id of a real entity for ownership and
segregation-of-duties checks to pass. Use the per-instance builders
make_inspector_headers(inspector_id) / make_caseworker_headers(caseworker_id) with
the actual entity id whenever a call is ownership- or SoD-gated. The shared
constants are only a fallback for tests that never exercise ownership (e.g. a
403/401/404/422 path, or GET-only reads).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # opaque operator role — shared constant is canonical.
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    # entity_backed roles — shared constants are non-ownership fallbacks only.
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "caseworker_headers": build_user_headers("test-caseworker-1", "Caseworker"),
}


def make_program_admin_headers(user_id: str = "test-admin-1") -> dict:
    """ProgramAdmin (opaque). user_id is recorded but not compared to any entity id."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_inspector_headers(user_id: str) -> dict:
    """For Inspector (entity_backed:Inspector). Pass the acting Inspector entity's id
    as user_id whenever the call references an inspector (ownership checks compare
    the resource's inspector_id to X-User-ID, PRD §2.1)."""
    return build_user_headers(user_id, "Inspector")


def make_caseworker_headers(user_id: str) -> dict:
    """For Caseworker (entity_backed:Caseworker). Pass the acting Caseworker entity's
    id as user_id whenever the call is segregation-of-duties-gated (compared to
    determined_by_caseworker_id / decided_by_caseworker_id, PRD §2.1, §2.8)."""
    return build_user_headers(user_id, "Caseworker")
