"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (ShopAdmin, Estimator, Fabricator,
# Scheduler) and for tests that do not exercise Contractor account ownership.
TEST_USERS = {
    "shop_admin_headers": build_user_headers("test-shop-admin-1", "ShopAdmin"),
    "estimator_headers": build_user_headers("test-estimator-1", "Estimator"),
    "fabricator_headers": build_user_headers("test-fabricator-1", "Fabricator"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "Scheduler"),
    # Contractor is entity_backed:ContractorAccount. The shared constant here is a
    # non-ownership fallback only; ownership-gated calls MUST use
    # make_contractor_headers(account_id) below.
    "contractor_headers": build_user_headers("test-contractor-1", "Contractor"),
}


def make_contractor_headers(account_id: str) -> dict:
    """For Contractor (entity_backed:ContractorAccount). Pass the actual
    ContractorAccount.id as X-User-ID whenever the call is ownership-gated
    (accept own quote, file claim on own job) — PRD §2.1."""
    return build_user_headers(account_id, "Contractor")


def make_unknown_role_headers() -> dict:
    """Headers carrying an unrecognized X-User-Role — used to exercise
    ERR_UNAUTHENTICATED (PRD §2.1)."""
    return build_user_headers("test-nobody-1", "Nobody")
