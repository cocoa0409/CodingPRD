"""Pre-built role headers for every role in the PRD.

ParkAdmin and RideOperator carry an opaque X-User-ID not tied to any entity, so
their shared constants are the canonical form. GuestApp is entity_backed:Guest —
ownership checks compare X-User-ID to the resource's guest_id (or a party's
leader_guest_id), so ownership-gated calls MUST use make_guest_headers(guest_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "park_admin_headers": build_user_headers("test-park-admin-1", "ParkAdmin"),
    "ride_operator_headers": build_user_headers("test-ride-operator-1", "RideOperator"),
    # GuestApp shared constant — fallback for non-ownership tests only
    # (e.g. 400/404 paths, RBAC checks that fail before ownership).
    "guest_app_headers": build_user_headers("test-guest-app-1", "GuestApp"),
}


def make_park_admin_headers() -> dict:
    """ParkAdmin (opaque)."""
    return TEST_USERS["park_admin_headers"]


def make_ride_operator_headers() -> dict:
    """RideOperator (opaque)."""
    return TEST_USERS["ride_operator_headers"]


def make_guest_headers(guest_id: str) -> dict:
    """For GuestApp (entity_backed:Guest). Pass the acting Guest.id (or the party's
    leader_guest_id) as user_id whenever the call is ownership-gated."""
    return build_user_headers(guest_id, "GuestApp")
