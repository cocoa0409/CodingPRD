"""Pre-built role headers for every role in the PRD.

Two roles are opaque operator identities (AccountManager, Dispatcher); two are
entity-backed (FieldTech -> Technician.tech_user_id, CustomerOwner ->
ServiceContract.customer_user_id). For entity-backed roles the X-User-ID must
match the backing entity's anchor field, so ownership/identity checks resolve.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "account_manager_headers": build_user_headers("am-1", "AccountManager"),
    "dispatcher_headers": build_user_headers("disp-1", "Dispatcher"),
    # Entity-backed roles: shared constant is a fallback for non-ownership tests only.
    "field_tech_headers": build_user_headers("tech-1", "FieldTech"),
    "customer_owner_headers": build_user_headers("owner-1", "CustomerOwner"),
}


# Per-instance builders — required for every entity-backed role.
def make_field_tech_headers(tech_user_id: str) -> dict:
    """For FieldTech (entity_backed:Technician). Pass the Technician's tech_user_id
    so the resolved Technician.id matches the resource's technician_id on
    ownership/identity-gated calls (visit start/rework, water-tests, quarantines,
    repairs, install start-build)."""
    return build_user_headers(tech_user_id, "FieldTech")


def make_customer_owner_headers(customer_user_id: str) -> dict:
    """For CustomerOwner (entity_backed:ServiceContract). Pass the
    ServiceContract.customer_user_id so ownership checks (dispute, approve,
    cancel feeding plan) resolve."""
    return build_user_headers(customer_user_id, "CustomerOwner")


def make_account_manager_headers(user_id: str = "am-1") -> dict:
    return build_user_headers(user_id, "AccountManager")


def make_dispatcher_headers(user_id: str = "disp-1") -> dict:
    return build_user_headers(user_id, "Dispatcher")
