"""Pre-built role headers for every role in the PRD.

GardenManager and Treasurer are opaque operator roles: a shared constant is the
canonical form. Gardener is entity-backed: for ownership-gated calls, thread the
actual Gardener.id via make_gardener_headers(gardener_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque roles: shared constant is canonical.
    "manager_headers": build_user_headers("test-manager-1", "GardenManager"),
    "treasurer_headers": build_user_headers("test-treasurer-1", "Treasurer"),
    # entity_backed Gardener: shared constant is a fallback for non-ownership tests
    # (e.g. RBAC-denied or shape-validation calls that never reach an ownership check).
    "gardener_headers": build_user_headers("test-gardener-1", "Gardener"),
}


def make_gardener_headers(user_id: str) -> dict:
    """For a Gardener (entity_backed:Gardener). Pass the actual Gardener.id as
    user_id whenever the call is ownership-gated (accept, decline, request-renewal,
    work-logs, water-readings, tool-loans, shed-bookings)."""
    return build_user_headers(user_id, "Gardener")


def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    return build_user_headers(user_id, "GardenManager")


def make_treasurer_headers(user_id: str = "test-treasurer-1") -> dict:
    return build_user_headers(user_id, "Treasurer")
