"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
# Designer, Scheduler, ManufacturingOps, PlatformAdmin all carry opaque identities
# (PRD 2.1), so their X-User-ID never needs to match a persisted entity.
TEST_USERS = {
    # Customer is entity_backed: this shared constant is a fallback for non-ownership
    # tests only (e.g. 401/403/404 paths). Ownership-gated calls must use the per-instance
    # builder below with the real Customer.id.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "designer_headers": build_user_headers("test-designer-1", "Designer"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "Scheduler"),
    "manufacturing_ops_headers": build_user_headers("test-mfgops-1", "ManufacturingOps"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated (cancel project, accept quote, request
    reschedule, submit financing, file warranty claim, create deposit/financing)."""
    return build_user_headers(user_id, "Customer")


def make_designer_headers(user_id: str = "test-designer-1") -> dict:
    return build_user_headers(user_id, "Designer")


def make_scheduler_headers(user_id: str = "test-scheduler-1") -> dict:
    return build_user_headers(user_id, "Scheduler")


def make_manufacturing_ops_headers(user_id: str = "test-mfgops-1") -> dict:
    return build_user_headers(user_id, "ManufacturingOps")


def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
