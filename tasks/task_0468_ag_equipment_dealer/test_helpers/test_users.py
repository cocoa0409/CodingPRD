"""Pre-built role headers for every role in the PRD.

All six roles carry an opaque identity (PRD §2.1): the X-User-ID is an opaque
operator identifier never compared to any entity's id, and authorization is
purely role-based. There are therefore no entity_backed roles and no per-instance
header builders — the shared constants below are the canonical form for every test.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "dealer_admin_headers": build_user_headers("test-dealeradmin-1", "DealerAdmin"),
    "sales_rep_headers": build_user_headers("test-salesrep-1", "SalesRep"),
    "finance_manager_headers": build_user_headers("test-financemanager-1", "FinanceManager"),
    "service_advisor_headers": build_user_headers("test-serviceadvisor-1", "ServiceAdvisor"),
    "parts_clerk_headers": build_user_headers("test-partsclerk-1", "PartsClerk"),
    "auction_clerk_headers": build_user_headers("test-auctionclerk-1", "AuctionClerk"),
}
