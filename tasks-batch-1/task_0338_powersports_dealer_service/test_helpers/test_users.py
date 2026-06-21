"""Pre-built role headers for every role in the PRD.

All five roles use an opaque X-User-ID that the server does not match against any
persisted entity's id (PRD 2.1). Authorization is decided solely by X-User-Role,
so shared-constant headers are the canonical form for every role.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "sales_manager_headers": build_user_headers("test-sales-1", "SalesManager"),
    "finance_manager_headers": build_user_headers("test-finance-1", "FinanceManager"),
    "service_advisor_headers": build_user_headers("test-service-1", "ServiceAdvisor"),
    "parts_clerk_headers": build_user_headers("test-parts-1", "PartsClerk"),
    "dealer_principal_headers": build_user_headers("test-principal-1", "DealerPrincipal"),
}
