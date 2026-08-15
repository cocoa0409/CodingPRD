"""Pre-built role headers for every role in the PRD (§2.1).

All seven roles are opaque operators: `X-User-ID` is not tied to any persisted
entity, so the shared constants below are the canonical form for every call.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "credit_manager_headers": build_user_headers("test-credit-manager-1", "CreditManager"),
    "estimator_headers": build_user_headers("test-estimator-1", "EstimatorUser"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "DispatcherUser"),
    "foreman_headers": build_user_headers("test-foreman-1", "Foreman"),
    "contractor_admin_headers": build_user_headers("test-contractor-admin-1", "ContractorAdmin"),
    "accounts_receivable_headers": build_user_headers("test-ar-clerk-1", "AccountsReceivableUser"),
    "warehouse_manager_headers": build_user_headers("test-warehouse-manager-1", "WarehouseManager"),
}
