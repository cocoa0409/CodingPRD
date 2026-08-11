"""Pre-built role headers for every role in the PRD.

PlatformAdmin and Dispatcher are opaque operator identities: their X-User-ID is
never compared against a persisted entity id, so shared constants are canonical.

Customer and Subcontractor are entity-backed: ownership and assignee checks
compare X-User-ID against the actual entity id, so any call whose success
depends on ownership MUST use make_customer_headers(customer["id"]) /
make_subcontractor_headers(subcontractor["id"]) with the real entity id.
The shared constants for those two roles are fallbacks for negative tests only.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constant is the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    # Entity-backed roles — fallback for non-ownership / negative tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "subcontractor_headers": build_user_headers("test-subcontractor-1", "Subcontractor"),
    # Anonymous marker — recognized nowhere; used only by negative auth tests.
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
}


def make_customer_headers(user_id: str) -> dict:
    """Customer is entity-backed: pass the actual Customer.id as user_id
    whenever the call is ownership-gated (verify-repair, dispute)."""
    return build_user_headers(user_id, "Customer")


def make_subcontractor_headers(user_id: str) -> dict:
    """Subcontractor is entity-backed: pass the actual Subcontractor.id as
    user_id whenever the call is assignee/authorship-gated (respond, check-in,
    complete-securing, install, record-removal, patrol check-in, assess, mitigate)."""
    return build_user_headers(user_id, "Subcontractor")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    return build_user_headers(user_id, "Dispatcher")
