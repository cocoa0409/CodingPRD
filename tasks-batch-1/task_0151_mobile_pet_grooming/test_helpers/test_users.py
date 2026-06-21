"""Pre-built role headers for every role in the PRD (§2.1).

PlatformAdmin and Dispatcher are opaque operator identities — their X-User-ID
is never compared to any entity id, so the shared constants are canonical.

Customer and Groomer are entity-backed: their X-User-ID must equal the acting
Customer.id / Groomer.id for ownership checks to pass. Use the make_* builders
with the real entity id whenever a call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   - admin / dispatcher: canonical (opaque roles).
#   - customer / groomer: fallback only for non-ownership tests (e.g. 404 / 422
#     on a missing or malformed resource where ownership never gets evaluated).
TEST_USERS = {
    "admin_headers": build_user_headers("admin-op-1", "PlatformAdmin"),
    "dispatcher_headers": build_user_headers("dispatcher-op-1", "Dispatcher"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "groomer_headers": build_user_headers("test-groomer-1", "Groomer"),
}


def make_admin_headers(user_id: str = "admin-op-1") -> dict:
    """PlatformAdmin (opaque). user_id is not compared to any entity."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_dispatcher_headers(user_id: str = "dispatcher-op-1") -> dict:
    """Dispatcher (opaque). user_id is not compared to any entity."""
    return build_user_headers(user_id, "Dispatcher")


def make_customer_headers(user_id: str) -> dict:
    """Customer (entity_backed:Customer). Pass the real Customer.id whenever the
    call is ownership-gated (own pets / appointments / plans / fee charges)."""
    return build_user_headers(user_id, "Customer")


def make_groomer_headers(user_id: str) -> dict:
    """Groomer (entity_backed:Groomer). Pass the real Groomer.id whenever the
    call is ownership-gated (completing an appointment assigned to them)."""
    return build_user_headers(user_id, "Groomer")
