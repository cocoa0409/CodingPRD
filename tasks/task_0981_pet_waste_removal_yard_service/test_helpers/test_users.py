"""Pre-built role headers for every role in the PRD.

Two roles are entity-backed (Customer, Technician) — for ownership-gated calls
the X-User-ID must equal the entity's id. Use make_customer_headers / make_technician_headers
with the actual entity id in those cases. OperationsManager and BillingAdmin
are opaque and safe to use as shared constants.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for non-ownership-gated calls.
TEST_USERS = {
    # entity_backed:Customer — shared fallback only for calls that do not
    # exercise ownership. For ownership-gated calls use make_customer_headers(customer_id).
    "customer_headers": build_user_headers("test-customer-shared", "Customer"),
    # entity_backed:Technician — same caveat; prefer make_technician_headers(tech_id).
    "technician_headers": build_user_headers("test-technician-shared", "Technician"),
    # opaque roles — canonical shared form.
    "ops_headers": build_user_headers("test-ops-1", "OperationsManager"),
    "billing_headers": build_user_headers("test-billing-1", "BillingAdmin"),
}


def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(customer_id, "Customer")


def make_technician_headers(technician_id: str) -> dict:
    """For Technician (entity_backed:Technician). Pass the actual Technician.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(technician_id, "Technician")


def make_ops_headers(user_id: str = "test-ops-1") -> dict:
    return build_user_headers(user_id, "OperationsManager")


def make_billing_headers(user_id: str = "test-billing-1") -> dict:
    return build_user_headers(user_id, "BillingAdmin")
