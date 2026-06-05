"""Pre-built role headers for every role in the PRD (PRD §2.1).

PRD §2.1: when X-User-Role is `Customer`, X-User-ID is the acting Customer.id and
ownership is enforced server-side; the other roles (Dispatcher, Technician,
PlatformAdmin) carry opaque operator identifiers. Customer is the only
entity-backed role — tests touching customer-owned resources MUST build headers
with `make_customer_headers(customer["id"])`. The shared `TEST_USERS["customer_headers"]`
constant is a fallback for tests that do not exercise ownership (e.g., 401 paths
or 404 against missing rows).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "technician_headers": build_user_headers("test-tech-1", "Technician"),
    # Entity-backed role — shared constant is a fallback for non-ownership tests.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # Anonymous — register-customer endpoint accepts no auth headers.
    "anonymous_headers": {},
}


def make_customer_headers(customer_id: str) -> dict:
    """Headers for the Customer role bound to a specific Customer.id.

    PRD §2.1 mandates that ownership-gated operations compare the resource's
    customer_id (directly or transitively) to X-User-ID. Tests that drive
    customer-owned writes MUST call this with the actual Customer.id.
    """
    return build_user_headers(customer_id, "Customer")


def make_dispatcher_headers(dispatcher_id: str = "test-dispatcher-1") -> dict:
    """Headers for the Dispatcher role (opaque operator id)."""
    return build_user_headers(dispatcher_id, "Dispatcher")


def make_technician_headers(technician_id: str = "test-tech-1") -> dict:
    """Headers for the Technician role (opaque operator id)."""
    return build_user_headers(technician_id, "Technician")


def make_admin_headers(admin_id: str = "test-admin-1") -> dict:
    """Headers for the PlatformAdmin role (opaque operator id)."""
    return build_user_headers(admin_id, "PlatformAdmin")


def make_headers(user_id: str, role: str) -> dict:
    """Generic constructor for parametrized RBAC tests."""
    return build_user_headers(user_id, role)
