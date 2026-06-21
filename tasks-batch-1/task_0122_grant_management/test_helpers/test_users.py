"""Pre-built role headers for every role in the Grant Management PRD (§2.1).

Every role carries an opaque identity (PRD §2.1): the server never compares
X-User-ID to any entity's id to establish ownership. Two recorded-identity
workflows do exist — drawdown initiation and report certification (PRD §2.1, §3.6) —
so a per-user FinanceOfficer builder is provided to drive the segregation-of-duties
check with deterministically distinct user ids.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for all roles since identity is opaque (no ownership gating).
TEST_USERS = {
    "grant_writer_headers": build_user_headers("user-grant-writer-1", "GrantWriter"),
    "finance_officer_headers": build_user_headers("user-finance-officer-1", "FinanceOfficer"),
    "program_manager_headers": build_user_headers("user-program-manager-1", "ProgramManager"),
    "agency_officer_headers": build_user_headers("user-agency-officer-1", "AgencyOfficer"),
    "auditor_headers": build_user_headers("user-auditor-1", "Auditor"),
}


def make_finance_officer_headers(user_id: str) -> dict:
    """FinanceOfficer headers with a caller-chosen X-User-ID.

    Used to thread a specific operator identity onto drawdown creation
    (recorded as initiated_by_user_id) and report certification
    (recorded as certified_by_user_id) for the PRD §3.6 segregation-of-duties rule.
    """
    return build_user_headers(user_id, "FinanceOfficer")


def make_grant_writer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "GrantWriter")


def make_program_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramManager")


def make_agency_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AgencyOfficer")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Auditor")


# Anonymous / unauthenticated: no auth headers at all (PRD §2.1 — missing
# X-User-ID / X-User-Role yields ERR_UNAUTHENTICATED).
ANONYMOUS_HEADERS: dict = {"Content-Type": "application/json"}
