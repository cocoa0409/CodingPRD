"""Pre-built role headers for every role in the PRD (§2.1).

All three roles use opaque X-User-ID values (PRD §2.1: the id is never compared
to any entity id). Distinct user ids are provided so segregation-of-duties tests
can control who submitted trial results vs who converts.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "program_admin_headers": build_user_headers("admin-1", "ProgramAdmin"),
    "account_manager_headers": build_user_headers("am-1", "AccountManager"),
    "ehs_officer_headers": build_user_headers("ehs-1", "EHSOfficer"),
}


def make_program_admin_headers(user_id: str) -> dict:
    """ProgramAdmin headers with a specific X-User-ID (e.g. SoD trials)."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_account_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AccountManager")


def make_ehs_officer_headers(user_id: str) -> dict:
    """EHSOfficer headers with a specific X-User-ID (submitter identity anchor)."""
    return build_user_headers(user_id, "EHSOfficer")
