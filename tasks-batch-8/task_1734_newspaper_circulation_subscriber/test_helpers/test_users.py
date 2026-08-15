"""Pre-built role headers for every role in PRD §2.1.

Subscriber is entity-backed: its X-User-ID must be the acting Subscriber's id
whenever the call is ownership-gated (own subscriptions, holds, complaints,
payments, charges, offers, own subscriber record). Use
make_subscriber_headers(subscriber["id"]) for those calls; the shared constant
is only safe for negative RBAC probes.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed:Subscriber — fallback for non-ownership probes only.
    "subscriber_headers": build_user_headers("test-subscriber-orphan", "Subscriber"),
    # opaque roles — shared constants are canonical.
    "service_rep_headers": build_user_headers("test-service-rep-1", "ServiceRep"),
    "district_manager_headers": build_user_headers("test-district-manager-1", "DistrictManager"),
    "circulation_director_headers": build_user_headers(
        "test-circulation-director-1", "CirculationDirector"
    ),
}

# Headers carrying a well-formed id but a role value outside the declared set.
INVALID_ROLE_HEADERS = {
    "X-User-ID": "anon-1",
    "X-User-Role": "Nobody",
    "Content-Type": "application/json",
}
# Headers missing X-User-ID / X-User-Role entirely.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_subscriber_headers(subscriber_id: str) -> dict:
    """Subscriber is entity-backed by Subscriber: pass the acting subscriber's
    id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(subscriber_id, "Subscriber")
