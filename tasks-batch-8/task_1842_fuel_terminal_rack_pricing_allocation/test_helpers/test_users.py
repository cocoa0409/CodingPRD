"""Pre-built role headers for every role in the PRD (§2.1).

All eight roles use opaque operator identifiers: the server never compares
X-User-ID against any persisted entity id, so shared constants are the
canonical form for every role.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "rack_price_analyst_headers": build_user_headers("test-price-analyst-1", "RackPriceAnalyst"),
    "allocation_manager_headers": build_user_headers("test-allocation-mgr-1", "AllocationManager"),
    "terminal_operator_headers": build_user_headers("test-terminal-op-1", "TerminalOperator"),
    "exchange_coordinator_headers": build_user_headers("test-exchange-coord-1", "ExchangeCoordinator"),
    "credit_analyst_headers": build_user_headers("test-credit-analyst-1", "CreditAnalyst"),
    "billing_clerk_headers": build_user_headers("test-billing-clerk-1", "BillingClerk"),
    "contract_admin_headers": build_user_headers("test-contract-admin-1", "ContractAdministrator"),
}

# Requests with no auth headers at all (PRD §2.1 -> ERR_UNAUTHENTICATED).
NO_AUTH_HEADERS: dict = {}
