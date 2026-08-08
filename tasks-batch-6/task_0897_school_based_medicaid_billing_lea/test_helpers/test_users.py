"""Pre-built role headers for every role in the PRD.

Three roles are opaque operator identities; ServiceProvider is entity-backed by a
Provider, so ownership-gated calls MUST use make_service_provider_headers(provider_id)
with the acting Provider's id rather than the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "medicaid_coordinator_headers": build_user_headers("test-mc-1", "MedicaidCoordinator"),
    "billing_coordinator_headers": build_user_headers("test-bc-1", "BillingCoordinator"),
    "state_reviewer_headers": build_user_headers("test-sr-1", "StateReviewer"),
    # Entity-backed role — shared constant is a fallback for non-ownership tests only.
    "service_provider_headers": build_user_headers("test-sp-1", "ServiceProvider"),
}


def make_service_provider_headers(provider_id: str) -> dict:
    """For ServiceProvider (entity_backed:Provider). Pass the acting Provider.id as
    the caller id whenever the call is ownership-gated (service-log create/document,
    moment respond)."""
    return build_user_headers(provider_id, "ServiceProvider")
