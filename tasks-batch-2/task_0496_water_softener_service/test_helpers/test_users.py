"""Pre-built role headers for every role in the PRD.

Two roles are entity-backed (FieldTech, Customer): ownership checks compare a
foreign key (a Route's tech_id, or the owning account's customer_id) against
X-User-ID. For those, prefer the per-instance builders below and pass the actual
entity id. The three remaining roles (ServiceManager, Dispatcher, BillingClerk)
are opaque operator identities not tied to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator identities — the shared constant is the canonical form.
    "service_manager_headers": build_user_headers("op-service-manager-1", "ServiceManager"),
    "dispatcher_headers": build_user_headers("op-dispatcher-1", "Dispatcher"),
    "billing_clerk_headers": build_user_headers("op-billing-clerk-1", "BillingClerk"),
    # Entity-backed roles — shared constant is a fallback for non-ownership tests only.
    "field_tech_headers": build_user_headers("entity-field-tech-1", "FieldTech"),
    "customer_headers": build_user_headers("entity-customer-1", "Customer"),
}


# Per-instance builders — required for every entity_backed role.
def make_field_tech_headers(tech_id: str) -> dict:
    """For FieldTech (entity_backed:FieldTech). Pass the actual FieldTech.id as
    X-User-ID whenever the call is ownership-gated (e.g. completing a stop on a
    route the tech is assigned to)."""
    return build_user_headers(tech_id, "FieldTech")


def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    X-User-ID whenever the call is ownership-gated (e.g. accepting a
    recommendation on the customer's own account, filing a claim)."""
    return build_user_headers(customer_id, "Customer")


def make_service_manager_headers(user_id: str = "op-service-manager-1") -> dict:
    return build_user_headers(user_id, "ServiceManager")


def make_dispatcher_headers(user_id: str = "op-dispatcher-1") -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_billing_clerk_headers(user_id: str = "op-billing-clerk-1") -> dict:
    return build_user_headers(user_id, "BillingClerk")
