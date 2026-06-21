"""Pre-built role headers for every role in the PRD.

The PRD recognizes exactly three roles. CurationAdmin and BillingOperator
are opaque operator roles: their X-User-ID is not matched against any entity,
so a shared constant is the canonical form. Subscriber is ownership-scoped:
its X-User-ID must equal the acting subscriber's own id, so ownership-gated
calls MUST use make_subscriber_headers(subscriber_id) with the real id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   - CurationAdmin / BillingOperator: opaque → shared constant is canonical.
#   - Subscriber: shared constant is a fallback for non-ownership tests only
#     (e.g. 401/404/400 paths that never reach an ownership check).
TEST_USERS = {
    "curation_admin_headers": build_user_headers("test-curation-admin-1", "CurationAdmin"),
    "billing_operator_headers": build_user_headers("test-billing-operator-1", "BillingOperator"),
    "subscriber_headers": build_user_headers("test-subscriber-1", "Subscriber"),
}


def make_subscriber_headers(subscriber_id: str) -> dict:
    """For Subscriber (entity_backed:Subscriber). Pass the actual Subscriber.id
    as user_id whenever the call is ownership-gated (pause/resume/cancel/winback/
    prepay/box-selections/gift purchase on the subscriber's own resources)."""
    return build_user_headers(subscriber_id, "Subscriber")


def make_curation_admin_headers(user_id: str = "test-curation-admin-1") -> dict:
    """CurationAdmin is opaque; user_id is recorded but never ownership-checked."""
    return build_user_headers(user_id, "CurationAdmin")


def make_billing_operator_headers(user_id: str = "test-billing-operator-1") -> dict:
    """BillingOperator is opaque; user_id is recorded but never ownership-checked."""
    return build_user_headers(user_id, "BillingOperator")
