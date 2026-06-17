"""Pre-built role headers for every role in the PRD (§2.1).

VenueManager and FrontDesk are opaque operator credentials — the server never
matches their X-User-ID against a stored entity, so a shared constant is the
canonical form. Customer is entity_backed: its X-User-ID must equal the acting
Customer entity's id, so ownership-gated calls MUST use make_customer_headers(id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# Customer ownership (e.g. 401/403/404/422 on missing or bad input).
TEST_USERS = {
    "venue_manager_headers": build_user_headers("test-venue-manager-1", "VenueManager"),
    "front_desk_headers": build_user_headers("test-front-desk-1", "FrontDesk"),
    # Fallback Customer constant — only for non-ownership tests (e.g. 403/401).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_venue_manager_headers(user_id: str = "test-venue-manager-1") -> dict:
    """VenueManager is opaque; the id is not entity-matched."""
    return build_user_headers(user_id, "VenueManager")


def make_front_desk_headers(user_id: str = "test-front-desk-1") -> dict:
    """FrontDesk is opaque; the id is not entity-matched."""
    return build_user_headers(user_id, "FrontDesk")


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual Customer.id
    as user_id whenever the call is ownership-gated (create/confirm/cancel/extend/
    queue/fb-order on the customer's own reservation)."""
    return build_user_headers(user_id, "Customer")
