"""Pre-built role headers for every role in the PRD (§2.1).

- Host and Manager are OPAQUE roles: X-User-ID is an operator identifier not
  tied to any persisted entity, so a shared constant is the canonical form.
- Customer is ENTITY-BACKED: X-User-ID must equal the acting Customer's id for
  ownership-gated calls (cancel/reschedule own reservation, cancel own waitlist
  entry). Use make_customer_headers(customer_id) with the real Customer.id in
  those cases. The shared TEST_USERS["customer_headers"] constant is a fallback
  only for non-ownership Customer calls (e.g. self-registration carries no auth,
  and reads/creates that the server does not ownership-gate by X-User-ID).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for opaque roles (Host, Manager); fallback only
# for non-ownership Customer calls.
TEST_USERS = {
    "manager_headers": build_user_headers("test-manager-1", "Manager"),
    "host_headers": build_user_headers("test-host-1", "Host"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}

# Anonymous: no auth headers at all (for ERR_UNAUTHENTICATED tests).
ANONYMOUS_HEADERS: dict = {}


def make_customer_headers(customer_id: str) -> dict:
    """For the entity-backed Customer role. Pass the actual Customer.id as
    customer_id whenever the call is ownership-gated."""
    return build_user_headers(customer_id, "Customer")


def make_host_headers(user_id: str = "test-host-1") -> dict:
    """Host is opaque; identity is a free-form operator id."""
    return build_user_headers(user_id, "Host")


def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    """Manager is opaque; identity is a free-form operator id."""
    return build_user_headers(user_id, "Manager")
