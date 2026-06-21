"""Pre-built role headers for every role in the PRD.

SecurityOfficer and LobbyAttendant are opaque operator identifiers (PRD 2.1):
their X-User-ID is free-form staff text, never compared to a persisted entity.
Host is entity-backed: X-User-ID equals a Host.id, so ownership and segregation
checks compare resource host foreign keys to X-User-ID. For any Host call that is
ownership-gated, build headers with the real Host.id via make_host_headers().
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# Host ownership.
TEST_USERS = {
    "security_officer_headers": build_user_headers("officer-1", "SecurityOfficer"),
    "lobby_attendant_headers": build_user_headers("attendant-1", "LobbyAttendant"),
    # Host: shared constant is a fallback for non-ownership tests only.
    "host_headers": build_user_headers("host-fallback-1", "Host"),
}


def make_security_officer_headers(user_id: str) -> dict:
    """SecurityOfficer with a specific X-User-ID. Used by segregation-of-duties
    tests where the officer's X-User-ID must (or must not) equal a Host.id."""
    return build_user_headers(user_id, "SecurityOfficer")


def make_lobby_attendant_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LobbyAttendant")


def make_host_headers(user_id: str) -> dict:
    """For Host (entity_backed:Host). Pass the actual Host.id as user_id whenever
    the call is ownership-gated."""
    return build_user_headers(user_id, "Host")
