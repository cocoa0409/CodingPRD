"""Pre-built role headers for every role in the PRD (§2.1).

Three roles are opaque operator identities (ProgramManager, HiringManager,
Finance): X-User-ID is not matched against any entity. The Supplier role is
entity_backed — X-User-ID must equal the acting Supplier entity's id for
ownership checks to pass, so a per-instance builder is provided.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise
# Supplier ownership.
TEST_USERS = {
    "program_manager_headers": build_user_headers("test-pm-1", "ProgramManager"),
    "hiring_manager_headers": build_user_headers("test-hm-1", "HiringManager"),
    "finance_headers": build_user_headers("test-fin-1", "Finance"),
    # Fallback for non-ownership Supplier tests only (e.g. 403/404 negatives).
    "supplier_headers": build_user_headers("test-sup-1", "Supplier"),
}


def make_program_manager_headers(user_id: str = "test-pm-1") -> dict:
    """ProgramManager is opaque; user_id is recorded but not matched."""
    return build_user_headers(user_id, "ProgramManager")


def make_hiring_manager_headers(user_id: str = "test-hm-1") -> dict:
    """HiringManager is opaque; user_id is recorded but not matched."""
    return build_user_headers(user_id, "HiringManager")


def make_finance_headers(user_id: str = "test-fin-1") -> dict:
    """Finance is opaque; user_id is recorded but not matched."""
    return build_user_headers(user_id, "Finance")


def make_supplier_headers(supplier_id: str) -> dict:
    """For the Supplier role (entity_backed:Supplier). Pass the actual
    Supplier.id as supplier_id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(supplier_id, "Supplier")
