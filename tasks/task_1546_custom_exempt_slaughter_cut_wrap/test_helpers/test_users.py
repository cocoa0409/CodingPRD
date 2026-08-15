"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (PlantOperator / PlantManager), whose
# X-User-ID is never compared to any entity id (PRD §2.1).
TEST_USERS = {
    "operator_headers": build_user_headers("test-operator-1", "PlantOperator"),
    "manager_headers": build_user_headers("test-manager-1", "PlantManager"),
    # Fallback for Customer in tests that do NOT exercise ownership
    # (e.g., unauthenticated/forbidden probes). Never use this constant for a
    # call whose success depends on owning the resource — use
    # make_customer_headers() with the real Customer.id instead.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity-backed). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (PRD §2.1: a Customer caller
    owns an appointment when its customer_id equals X-User-ID, owns a share
    via owner_customer_id, and owns invoices/storage/labels/cut-sheets through
    the share)."""
    return build_user_headers(user_id, "Customer")
