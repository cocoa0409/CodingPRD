"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
# Four roles carry an opaque identity (PlatformAdmin, CatalogManager,
# ProductionOperator, SalesAgent): the X-User-ID is never compared to any
# entity id, so a shared constant is the canonical form for them.
# The Wholesaler role is entity-backed (X-User-ID is the acting
# WholesaleAccount.id); the shared constant is a fallback for tests that do NOT
# exercise ownership — use make_wholesaler_headers(account_id) otherwise.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "catalog_headers": build_user_headers("test-catalog-1", "CatalogManager"),
    "production_headers": build_user_headers("test-production-1", "ProductionOperator"),
    "sales_headers": build_user_headers("test-sales-1", "SalesAgent"),
    "wholesaler_headers": build_user_headers("test-wholesaler-1", "Wholesaler"),
}


def make_wholesaler_headers(account_id: str) -> dict:
    """For the Wholesaler role (entity_backed:WholesaleAccount). Pass the actual
    WholesaleAccount.id as X-User-ID whenever the call is ownership-gated."""
    return build_user_headers(account_id, "Wholesaler")
