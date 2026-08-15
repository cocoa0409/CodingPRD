"""Pre-built role headers for every role in the PRD (§2.1).

All four roles are opaque: X-User-ID is an operator identifier never compared
against any resource id. It IS compared against other operator identifiers for
segregation of duties (write-off creator vs approver vs reverser), so builders
accepting an explicit user_id are provided for each role.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical operator identities used across tests.
TEST_USERS = {
    "collector_headers": build_user_headers("collector-1", "Collector"),
    "counselor_headers": build_user_headers("counselor-1", "FinancialCounselor"),
    "officer_headers": build_user_headers("officer-1", "RevenueIntegrityOfficer"),
    "agency_headers": build_user_headers("agency-1", "CollectionAgencyUser"),
}


def make_collector_headers(user_id: str = "collector-1") -> dict:
    return build_user_headers(user_id, "Collector")


def make_counselor_headers(user_id: str = "counselor-1") -> dict:
    return build_user_headers(user_id, "FinancialCounselor")


def make_officer_headers(user_id: str = "officer-1") -> dict:
    return build_user_headers(user_id, "RevenueIntegrityOfficer")


def make_agency_headers(user_id: str = "agency-1") -> dict:
    return build_user_headers(user_id, "CollectionAgencyUser")
