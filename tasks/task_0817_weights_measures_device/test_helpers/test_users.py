"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants.
#   ProgramAdmin identity is opaque (PRD §2.1): the shared constant is canonical.
#   Inspector / Establishment are entity_backed: the shared constant is a fallback
#   used ONLY for tests that do not exercise ownership (e.g. 401/403/404 paths).
TEST_USERS = {
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "establishment_headers": build_user_headers("test-establishment-1", "Establishment"),
}


def make_program_admin_headers(user_id: str = "test-admin-1") -> dict:
    """ProgramAdmin (opaque identity). Any user_id is accepted, never ownership-checked."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_inspector_headers(user_id: str) -> dict:
    """For Inspector (entity_backed:Inspector). Pass the actual Inspector.id."""
    return build_user_headers(user_id, "Inspector")


def make_establishment_headers(user_id: str) -> dict:
    """For Establishment (entity_backed:Establishment). Pass the actual Establishment.id
    whenever the call is ownership-gated (paying own penalties / invoices, PRD §2.1)."""
    return build_user_headers(user_id, "Establishment")
