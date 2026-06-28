"""Pre-built role headers for every role in the PRD.

Two of the four roles (Dispatcher, BillingAdmin) are opaque operator identities whose
X-User-ID is never compared to any entity (PRD §2.1) — the shared constants below are the
canonical form for them. The other two roles (FieldTech, Customer) are entity-backed: their
ownership-gated calls must use the per-instance builders with the owning entity's id (PRD §2.1).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator roles — shared constants are canonical.
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "billing_admin_headers": build_user_headers("test-billing-admin-1", "BillingAdmin"),
    # entity_backed roles — shared constants are a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "field_tech_headers": build_user_headers("test-field-tech-1", "FieldTech"),
}


def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the owning Customer.id as the user id
    whenever the call is ownership-gated (accept/decline a quote, dispute an invoice,
    file a claim on an owned visit)."""
    return build_user_headers(customer_id, "Customer")


def make_field_tech_headers(technician_id: str) -> dict:
    """For FieldTech (entity_backed:Technician). Pass the acting Technician.id as the user id
    whenever the call is ownership-gated (start/complete a visit, upload photos)."""
    return build_user_headers(technician_id, "FieldTech")
