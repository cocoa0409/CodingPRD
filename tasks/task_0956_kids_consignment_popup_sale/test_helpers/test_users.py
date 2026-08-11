"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (Anonymous, EventOrganizer, Cashier)
# whose X-User-ID is never compared to any entity id (PRD §2.1), and for
# entity-backed roles in tests that do not exercise an ownership check.
TEST_USERS = {
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    "organizer_headers": build_user_headers("test-organizer-1", "EventOrganizer"),
    "cashier_headers": build_user_headers("test-cashier-1", "Cashier"),
    # Fallbacks for entity-backed roles: use ONLY where ownership is not exercised.
    "consignor_headers": build_user_headers("test-consignor-1", "Consignor"),
    "volunteer_headers": build_user_headers("test-volunteer-1", "Volunteer"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
}


# Per-instance builders — required for entity-backed roles whenever the call is
# ownership-gated (PRD §2.1: X-User-ID must equal the acting entity's id).
def make_consignor_headers(user_id: str) -> dict:
    """Consignor role: X-User-ID must be the acting Consignor's id."""
    return build_user_headers(user_id, "Consignor")


def make_volunteer_headers(user_id: str) -> dict:
    """Volunteer role: X-User-ID must be the acting Volunteer's id."""
    return build_user_headers(user_id, "Volunteer")


def make_inspector_headers(user_id: str) -> dict:
    """Inspector role: X-User-ID must be the acting Volunteer's id (PRD §2.1)."""
    return build_user_headers(user_id, "Inspector")
