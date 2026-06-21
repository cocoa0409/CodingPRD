"""Pre-built role headers for every role in the PRD.

PRD §2.1: exactly five roles — Customer, Estimator, Dispatcher, ClaimsAdjuster,
PlatformAdmin. Only Customer's X-User-ID is entity-backed (it must equal the
acting Customer's id for ownership-gated calls); the other four are opaque
operator identifiers not tied to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# Customer ownership. The Customer shared constant is a fallback usable only for
# non-ownership scenarios (e.g. POST /customers, POST /move-jobs validation).
TEST_USERS = {
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "estimator_headers": build_user_headers("test-estimator-1", "Estimator"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "claims_adjuster_headers": build_user_headers("test-adjuster-1", "ClaimsAdjuster"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


# ─── Per-instance builders ────────────────────────────────────────────────────
def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (accept / cancel / payments)."""
    return build_user_headers(user_id, "Customer")


def make_estimator_headers(user_id: str = "test-estimator-1") -> dict:
    """For Estimator (opaque). user_id is recorded as estimator_user_id."""
    return build_user_headers(user_id, "Estimator")


def make_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    """For Dispatcher (opaque)."""
    return build_user_headers(user_id, "Dispatcher")


def make_claims_adjuster_headers(user_id: str) -> dict:
    """For ClaimsAdjuster (opaque). user_id is recorded as filed_by_user_id at
    filing and adjudicated_by_user_id at approve/deny; the two are compared to
    enforce segregation of duties, so tests must control this value."""
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    """For PlatformAdmin (opaque superuser)."""
    return build_user_headers(user_id, "PlatformAdmin")
