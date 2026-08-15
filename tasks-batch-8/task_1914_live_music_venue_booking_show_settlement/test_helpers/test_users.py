"""Pre-built role headers for every role in PRD §2.1.

BookingAgent is entity-backed: its X-User-ID must equal the acting
BookingAgent entity's id whenever the call is ownership-gated (date-hold
place/challenge/confirm/release). Use make_booking_agent_headers(agent["id"])
for those calls; the shared constant is a fallback only for non-ownership
probes (e.g. negative RBAC, 404-on-missing-resource).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "venue_manager_headers": build_user_headers("vm-1", "VenueManager"),
    # entity_backed:BookingAgent — fallback for non-ownership probes only.
    "booking_agent_headers": build_user_headers("agent-orphan-1", "BookingAgent"),
    "promoter_headers": build_user_headers("prom-1", "Promoter"),
    "production_manager_headers": build_user_headers("pm-1", "ProductionManager"),
    "accountant_headers": build_user_headers("acct-1", "Accountant"),
}

# Header sets used to probe authentication failures (PRD §2.1).
ANONYMOUS_HEADERS = {"X-User-ID": "anon-1", "Content-Type": "application/json"}
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_booking_agent_headers(agent_id: str) -> dict:
    """BookingAgent is entity-backed: pass the acting BookingAgent's id
    whenever the call is ownership-gated (place/challenge/confirm/release)."""
    return build_user_headers(agent_id, "BookingAgent")


def make_venue_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "VenueManager")


def make_promoter_headers(user_id: str) -> dict:
    """Promoter identity is opaque but recorded as submitted_by_user_id."""
    return build_user_headers(user_id, "Promoter")


def make_accountant_headers(user_id: str) -> dict:
    """Accountant identity is opaque but recorded as approved_by_user_id."""
    return build_user_headers(user_id, "Accountant")


def make_production_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionManager")
