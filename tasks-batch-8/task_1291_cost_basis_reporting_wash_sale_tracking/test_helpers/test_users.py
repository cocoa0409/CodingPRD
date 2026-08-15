"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. Customer is entity-backed: for ownership-gated calls, use
# make_customer_headers(<Customer.id>) instead of the shared constant.
TEST_USERS = {
    "firm_admin_headers": build_user_headers("firmadmin-1", "FirmAdmin"),
    "tax_ops_headers": build_user_headers("taxops-1", "TaxOps"),
    "customer_service_headers": build_user_headers("cs-1", "CustomerService"),
    "auditor_headers": build_user_headers("auditor-1", "Auditor"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("customer-fallback-1", "Customer"),
}


def make_firm_admin_headers(user_id: str = "firmadmin-1") -> dict:
    return build_user_headers(user_id, "FirmAdmin")


def make_tax_ops_headers(user_id: str = "taxops-1") -> dict:
    """Distinct TaxOps user ids are needed for segregation-of-duties tests."""
    return build_user_headers(user_id, "TaxOps")


def make_customer_service_headers(user_id: str = "cs-1") -> dict:
    return build_user_headers(user_id, "CustomerService")


def make_auditor_headers(user_id: str = "auditor-1") -> dict:
    return build_user_headers(user_id, "Auditor")


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (own-record reads, basis
    change request submission, resubmit)."""
    return build_user_headers(user_id, "Customer")
