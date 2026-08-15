"""Pre-built role headers for every role in the PRD (§2.1).

All four roles are opaque operator identities: the server never compares
X-User-ID against any persisted entity id, so shared constants are canonical.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "registrar_headers": build_user_headers("test-registrar-1", "Registrar"),
    "financial_counselor_headers": build_user_headers(
        "test-financial-counselor-1", "FinancialCounselor"
    ),
    "front_desk_headers": build_user_headers("test-front-desk-1", "FrontDeskAgent"),
    "access_supervisor_headers": build_user_headers(
        "test-access-supervisor-1", "AccessSupervisor"
    ),
}
