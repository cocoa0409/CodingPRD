"""Pre-built role headers for every role in the PRD (§2.1).

ContractAdmin and Dispatcher are opaque operator identities; their X-User-ID is not
compared to any persisted entity, so the shared constants are the canonical form.

Technician and Customer are entity-backed: their X-User-ID must equal the acting
Technician.id / Customer.id for ownership-gated calls. Use the per-instance builders
(make_technician_headers / make_customer_headers) with the real entity id whenever the
call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared constants.
    "contract_admin_headers": build_user_headers("admin-1", "ContractAdmin"),
    "dispatcher_headers": build_user_headers("dispatcher-1", "Dispatcher"),
    # Entity-backed roles — shared constants are a fallback for NON-ownership tests only
    # (e.g. a role-denial 403 that fails before any ownership check, or a 404 on a
    # missing resource). For ownership-gated calls, use the builders below instead.
    "technician_headers": build_user_headers("technician-fallback-1", "Technician"),
    "customer_headers": build_user_headers("customer-fallback-1", "Customer"),
}


def make_technician_headers(user_id: str) -> dict:
    """For Technician (entity_backed:Technician). Pass the actual Technician.id as
    user_id for any depart/arrive/complete/refrigerant/part call gated on
    visit.technician_id == X-User-ID (PRD §2.1, §3.7)."""
    return build_user_headers(user_id, "Technician")


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as user_id
    for any read/cancel/accept/decline gated on the owning customer_id chain
    (PRD §2.1)."""
    return build_user_headers(user_id, "Customer")


# Headers for an anonymous (unauthenticated) request: no X-User-ID / X-User-Role.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}
