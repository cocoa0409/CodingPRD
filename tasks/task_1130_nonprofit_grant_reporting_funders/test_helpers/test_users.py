"""Pre-built role headers for every role in the PRD (§2.1).

Funder is entity-backed: when a funder-scoped action is exercised (start-review,
accept, return, approve, deny, decide), the caller's X-User-ID MUST equal the
id of the Funder entity that awarded the grant — use make_funder_headers(funder_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# funder ownership (400/404 paths, system-admin clock calls, etc.).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "SystemAdmin"),
    "officer_headers": build_user_headers("officer-1", "GrantsOfficer"),
    "officer2_headers": build_user_headers("officer-2", "GrantsOfficer"),
    "finance_headers": build_user_headers("fin-1", "FinanceManager"),
    "finance2_headers": build_user_headers("fin-2", "FinanceManager"),
    "director_headers": build_user_headers("director-1", "ProgramDirector"),
    "auditor_headers": build_user_headers("auditor-1", "Auditor"),
    # Fallback for the entity-backed Funder role — only for tests where the
    # ownership check is not the behavior under test.
    "funder_headers": build_user_headers("test-funder-1", "Funder"),
}


def make_funder_headers(funder_id: str) -> dict:
    """Funder is entity-backed: X-User-ID must equal the Funder.id that owns
    the grant whenever the call is funder-scoped (PRD §2.1)."""
    return build_user_headers(funder_id, "Funder")


def make_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "GrantsOfficer")


def make_finance_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceManager")


def make_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramDirector")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Auditor")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SystemAdmin")
