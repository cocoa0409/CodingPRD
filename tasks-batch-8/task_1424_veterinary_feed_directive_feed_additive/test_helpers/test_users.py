"""Pre-built role headers for every role in the PRD (§2.1).

Identity binding (PRD §2.1): Veterinarian/FeedMillOperator/Producer are
entity-backed — X-User-ID must be the acting entity's id for ownership-gated
calls. Use the make_*_headers builders with the real entity id in those cases.
Inspector is opaque — the shared constant is canonical.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role: canonical shared constant.
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    # Entity-backed roles: shared constants are fallbacks for non-ownership
    # tests only (bad payload, missing resource, RBAC denials).
    "veterinarian_headers": build_user_headers("test-vet-1", "Veterinarian"),
    "feed_mill_operator_headers": build_user_headers("test-mill-1", "FeedMillOperator"),
    "producer_headers": build_user_headers("test-producer-1", "Producer"),
}


def make_inspector_headers(user_id: str = "test-inspector-1") -> dict:
    """Inspector is an opaque identity; any user id is acceptable."""
    return build_user_headers(user_id, "Inspector")


def make_veterinarian_headers(vet_id: str) -> dict:
    """Veterinarian is entity-backed: pass the acting Veterinarian.id."""
    return build_user_headers(vet_id, "Veterinarian")


def make_feed_mill_operator_headers(feed_mill_id: str) -> dict:
    """FeedMillOperator is entity-backed: pass the acting FeedMill.id."""
    return build_user_headers(feed_mill_id, "FeedMillOperator")


def make_producer_headers(producer_id: str) -> dict:
    """Producer is entity-backed: pass the acting Producer.id."""
    return build_user_headers(producer_id, "Producer")
