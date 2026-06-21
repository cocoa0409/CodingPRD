"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the three opaque operator roles (IntakeClerk,
# Estimator, ShopManager), whose X-User-ID is never compared to any entity id.
# The customer constant is a fallback for tests that do NOT exercise ownership
# (e.g. 403-forbidden-role or 404-not-found checks); ownership-gated customer
# calls MUST use make_customer_headers(customer_id) with the real Customer id.
TEST_USERS = {
    "intake_clerk_headers": build_user_headers("clerk-001", "IntakeClerk"),
    "estimator_headers": build_user_headers("estimator-001", "Estimator"),
    "shop_manager_headers": build_user_headers("manager-001", "ShopManager"),
    "customer_headers": build_user_headers("customer-001", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual Customer.id
    as user_id whenever the call is ownership-gated (approve / decline /
    request-revision / file warranty claim)."""
    return build_user_headers(user_id, "Customer")
