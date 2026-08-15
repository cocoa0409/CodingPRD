"""Pre-built role headers for every role in the PRD (section 2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the opaque (non-entity-backed) roles. Safe for every
# call that is not ownership-gated.
TEST_USERS = {
    "plant_admin_headers": build_user_headers("test-plant-admin-1", "PlantAdmin"),
    "sales_rep_headers": build_user_headers("test-sales-rep-1", "SalesRep"),
    "production_planner_headers": build_user_headers(
        "test-prod-planner-1", "ProductionPlanner"
    ),
    "customer_service_headers": build_user_headers("cs-100", "CustomerService"),
    "claims_adjuster_headers": build_user_headers("adj-200", "ClaimsAdjuster"),
    # entity_backed role: shared constant is a fallback for non-ownership
    # tests only; ownership-gated calls MUST use make_customer_headers().
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:CustomerAccount). Pass the actual
    CustomerAccount.id as user_id whenever the call is ownership-gated
    (release creation / release cancellation)."""
    return build_user_headers(user_id, "Customer")


def make_customer_service_headers(user_id: str) -> dict:
    """CustomerService operator headers with a specific X-User-ID (claims
    filer identity is stamped as filed_by_user_id)."""
    return build_user_headers(user_id, "CustomerService")


def make_claims_adjuster_headers(user_id: str) -> dict:
    """ClaimsAdjuster operator headers with a specific X-User-ID (stamped as
    adjudicated_by_user_id at resolution)."""
    return build_user_headers(user_id, "ClaimsAdjuster")


# Headers carrying no authentication identity at all (401 scenarios).
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}
