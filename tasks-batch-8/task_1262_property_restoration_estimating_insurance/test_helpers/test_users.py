"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque roles and for tests that do not
# exercise Customer ownership.
TEST_USERS = {
    "contractor_admin_headers": build_user_headers("test-admin-1", "ContractorAdmin"),
    "estimator_headers": build_user_headers("test-estimator-1", "Estimator"),
    "field_technician_headers": build_user_headers("test-tech-1", "FieldTechnician"),
    "adjuster_headers": build_user_headers("test-adjuster-1", "Adjuster"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """Customer is entity-backed: X-User-ID must be the acting Customer.id for
    ownership-gated calls (claim reads, WA signing, DEDUCTIBLE payments)."""
    return build_user_headers(user_id, "Customer")


def make_contractor_admin_headers(user_id: str) -> dict:
    """Opaque role, but a distinct X-User-ID is required to exercise the
    invoice-void segregation-of-duties rule (created_by_user_id)."""
    return build_user_headers(user_id, "ContractorAdmin")


def make_estimator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Estimator")


def make_adjuster_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Adjuster")


def make_field_technician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FieldTechnician")
