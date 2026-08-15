"""Pre-built role headers for the three PRD roles.

ProgramAdmin is an opaque role: its X-User-ID is not tied to any entity, so the
shared constant is canonical. Volunteer and Member are entity-backed roles:
whenever a call is ownership-gated or actor-recorded (nominated_by, reviewer
identity), the caller's X-User-ID MUST be the actual entity's id — use the
per-instance builders below. The shared Volunteer/Member constants exist only
for tests whose outcome never depends on caller identity resolution (e.g.
bad-payload 400s) — never for ownership-gated calls.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque role: canonical shared form
    "program_admin_headers": build_user_headers("test-program-admin-1", "ProgramAdmin"),
    # entity-backed roles: fallback only, do NOT use for ownership-gated calls
    "volunteer_headers": build_user_headers("test-volunteer-fallback", "Volunteer"),
    "member_headers": build_user_headers("test-member-fallback", "Member"),
}

# Headers carrying no credentials at all (for ERR_UNAUTHENTICATED tests).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_volunteer_headers(user_id: str) -> dict:
    """For Volunteer (entity-backed). Pass the actual Volunteer.id as user_id
    whenever the call records or checks the acting volunteer."""
    return build_user_headers(user_id, "Volunteer")


def make_member_headers(user_id: str) -> dict:
    """For Member (entity-backed). Pass the actual Member.id as user_id
    whenever the call is member-scoped or records the acting member."""
    return build_user_headers(user_id, "Member")


def make_program_admin_headers(user_id: str = "test-program-admin-1") -> dict:
    """For ProgramAdmin (opaque): any identifier works."""
    return build_user_headers(user_id, "ProgramAdmin")
