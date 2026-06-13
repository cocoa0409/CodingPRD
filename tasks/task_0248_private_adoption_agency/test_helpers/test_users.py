"""Pre-built role headers for every role in the PRD (Private Adoption Agency API).

All five roles carry an OPAQUE identity (PRD §2.1): X-User-ID is an operator
identifier never compared to any persisted entity's id. The server records the
acting X-User-ID onto resources (e.g. authoring_caseworker_id, logged_by_caseworker_id)
and segregation-of-duties checks compare those recorded identifiers against one
another — never against a resource id. Therefore the shared constants below are
the canonical form for every role; for segregation-of-duties scenarios that need
two DISTINCT operators of the same role, build extra headers with
build_user_headers(<distinct-id>, <role>).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "agency_admin_headers": build_user_headers("admin-1", "AgencyAdmin"),
    "supervisor_headers": build_user_headers("sup-1", "Supervisor"),
    "caseworker_headers": build_user_headers("cw-1", "Caseworker"),
    "finance_officer_headers": build_user_headers("fo-1", "FinanceOfficer"),
    "compact_admin_headers": build_user_headers("ca-1", "CompactAdministrator"),
}


def make_agency_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AgencyAdmin")


def make_supervisor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Supervisor")


def make_caseworker_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Caseworker")


def make_finance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceOfficer")


def make_compact_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CompactAdministrator")
