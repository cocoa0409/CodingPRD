"""Pre-built role headers for every role in the PRD (§2.1).

Subscriber is entity-backed: when a call is ownership-gated, the X-User-ID
must be the acting Subscriber's id — use make_subscriber_headers(subscriber_id).
Driver and OperationsManager ids are opaque operator identifiers; they are
recorded as tagged_by_driver_id / resolved_by and anchor segregation of duties.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "driver_headers": build_user_headers("drv-1", "Driver"),
    "driver2_headers": build_user_headers("drv-2", "Driver"),
    "ops_headers": build_user_headers("ops-1", "OperationsManager"),
    "ops2_headers": build_user_headers("ops-2", "OperationsManager"),
    # Entity-backed role: fallback ONLY for tests that do not exercise
    # ownership (e.g., 400/404 shape checks). Ownership-gated calls MUST use
    # make_subscriber_headers(subscriber["id"]).
    "subscriber_headers": build_user_headers("test-subscriber-1", "Subscriber"),
}


def make_subscriber_headers(user_id: str) -> dict:
    """Subscriber is entity-backed: pass the actual Subscriber.id as user_id
    whenever the call is ownership-gated (own subscriptions, pickups, tags,
    credit entries, redemptions, invoices)."""
    return build_user_headers(user_id, "Subscriber")


def make_driver_headers(user_id: str) -> dict:
    """Driver ids are opaque operator ids (recorded as tagged_by_driver_id)."""
    return build_user_headers(user_id, "Driver")


def make_ops_headers(user_id: str) -> dict:
    """OperationsManager ids are opaque operator ids (recorded as resolved_by)."""
    return build_user_headers(user_id, "OperationsManager")


def make_anonymous_headers(user_id: str) -> dict:
    """Anonymous ids are opaque; used only for the self-signup operation."""
    return build_user_headers(user_id, "Anonymous")
