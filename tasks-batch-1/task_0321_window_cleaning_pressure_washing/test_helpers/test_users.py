"""Pre-built role headers for every role in the Window Cleaning PRD (§2.1).

Three of the four roles are opaque operator identities (Dispatcher, FieldCrew,
Billing): their X-User-ID is recorded but never compared to any entity, so the
shared constant is the canonical form. The Customer role is entity-backed
(X-User-ID is the acting Account.id, PRD §2.1): ownership checks compare a
resource's account FK to X-User-ID. For ownership-gated Customer calls use the
per-instance builder make_customer_headers(account_id) — never the shared
fallback, whose id never equals any real Account.id.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constant is canonical.
    "dispatcher_headers": build_user_headers("dispatcher-1", "Dispatcher"),
    "field_crew_headers": build_user_headers("fieldcrew-1", "FieldCrew"),
    "billing_headers": build_user_headers("billing-1", "Billing"),
    # Customer (entity_backed:Account) — fallback usable ONLY for tests that do
    # not exercise ownership (e.g. a 401/403 that fires before any ownership
    # check). Ownership-gated calls MUST use make_customer_headers(account_id).
    "customer_headers": build_user_headers("customer-fallback-1", "Customer"),
}


def make_customer_headers(account_id: str) -> dict:
    """For the Customer role (entity_backed:Account). Pass the acting Account.id
    so ownership checks comparing a resource's account FK to X-User-ID resolve."""
    return build_user_headers(account_id, "Customer")


def make_dispatcher_headers(user_id: str = "dispatcher-1") -> dict:
    """Dispatcher is opaque; user_id is recorded but never compared."""
    return build_user_headers(user_id, "Dispatcher")


def make_field_crew_headers(user_id: str = "fieldcrew-1") -> dict:
    """FieldCrew is opaque; user_id is recorded but never compared."""
    return build_user_headers(user_id, "FieldCrew")


def make_billing_headers(user_id: str = "billing-1") -> dict:
    """Billing is opaque; user_id is recorded but never compared."""
    return build_user_headers(user_id, "Billing")
