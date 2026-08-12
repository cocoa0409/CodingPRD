"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque ClubAdmin role and for tests that do
# not exercise ownership (404 / 400 / role-list checks). Entity-backed roles
# must use the per-instance builders below whenever the call is ownership-gated
# or the caller's X-User-ID must reference an existing Member.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "ClubAdmin"),
    # Entity-backed roles: shared constants are fallbacks for non-ownership
    # tests only (e.g. role-list rejections where no member row is needed by
    # the caller's identity... note the PRD requires the id to reference an
    # existing member, so prefer the builders).
    "member_headers": build_user_headers("test-member-1", "Member"),
    "netcontrol_headers": build_user_headers("test-netcontrol-1", "NetControl"),
    "ec_headers": build_user_headers("test-ec-1", "EmergencyCoordinator"),
    "liaison_headers": build_user_headers("test-liaison-1", "ExamLiaison"),
}


def make_member_headers(user_id: str) -> dict:
    """For Member (entity-backed): pass the actual Member.id."""
    return build_user_headers(user_id, "Member")


def make_netcontrol_headers(user_id: str) -> dict:
    """For NetControl (entity-backed): pass the acting Member.id; the caller
    owns exactly the nets whose net_control_member_id equals it."""
    return build_user_headers(user_id, "NetControl")


def make_ec_headers(user_id: str) -> dict:
    """For EmergencyCoordinator (entity-backed): pass the acting Member.id."""
    return build_user_headers(user_id, "EmergencyCoordinator")


def make_liaison_headers(user_id: str) -> dict:
    """For ExamLiaison (entity-backed): pass the acting Member.id."""
    return build_user_headers(user_id, "ExamLiaison")
