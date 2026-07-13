"""Pre-built role headers for every role in the Marine Dealer PRD.

All four roles are opaque operator identifiers (PRD §2.1): X-User-ID is never
compared to any resource id, so shared constants are the canonical form for
every role. No per-instance builders are needed.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "manager_headers": build_user_headers("op-manager-1", "Manager"),
    "sales_rep_headers": build_user_headers("op-sales-1", "SalesRep"),
    "service_advisor_headers": build_user_headers("op-service-1", "ServiceAdvisor"),
    "parts_clerk_headers": build_user_headers("op-parts-1", "PartsClerk"),
    # An unrecognized role — used only for the authentication-rejection test.
    "unknown_role_headers": build_user_headers("op-anon-1", "Anonymous"),
}
