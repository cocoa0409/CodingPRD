"""Pre-built role headers for every role in the PRD.

All four roles are opaque identifiers. PlatformAdmin / VenueOperator / GateAttendant
X-User-IDs are never compared to any entity id. For Patron, X-User-ID carries ownership
meaning: it is matched against the patron_id recorded on reservations, season passes, and
(via the owning reservation) concession orders. Tests that exercise Patron ownership must
therefore use make_patron_headers(patron_id) with the SAME patron_id supplied at creation.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque operator roles, and for Patron tests that do
# not exercise ownership (e.g. read-only GETs, 401/403/404 paths).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "venue_operator_headers": build_user_headers("operator-1", "VenueOperator"),
    "gate_attendant_headers": build_user_headers("gate-1", "GateAttendant"),
    # Generic patron header — only for non-ownership tests; ownership tests must use
    # make_patron_headers(patron_id) with the matching patron_id.
    "patron_headers": build_user_headers("patron-generic", "Patron"),
}


def make_platform_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_venue_operator_headers(user_id: str = "operator-1") -> dict:
    return build_user_headers(user_id, "VenueOperator")


def make_gate_attendant_headers(user_id: str = "gate-1") -> dict:
    return build_user_headers(user_id, "GateAttendant")


def make_patron_headers(patron_id: str) -> dict:
    """For Patron operations. Pass the patron_id stored on the owned resource so the
    server's ownership check (X-User-ID == resource.patron_id) succeeds."""
    return build_user_headers(patron_id, "Patron")


def anonymous_headers() -> dict:
    """Headers with no X-User-Role / X-User-ID — used for ERR_UNAUTHENTICATED tests."""
    return {"Content-Type": "application/json"}
