"""Pre-built role headers for every role in the PRD.

All five roles in this domain are operator identities with an opaque X-User-ID
(PRD §2.1): "the corresponding X-User-ID is an opaque operator identifier that is
not tied to any stored entity; the server ... never compares it to any entity's id,
and ownership of a resource is never determined by matching X-User-ID against a
stored field." Authorization is purely role-based. The shared constants below are
therefore the canonical form for every role; the per-id builders exist only for
threading a distinct operator id through a workflow when a test wants one.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — canonical for every (opaque) role.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "floor_manager_headers": build_user_headers("floor-1", "FloorManager"),
    "door_host_headers": build_user_headers("door-1", "DoorHost"),
    "bartender_headers": build_user_headers("bar-1", "Bartender"),
    "security_officer_headers": build_user_headers("sec-1", "SecurityOfficer"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_floor_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FloorManager")


def make_door_host_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DoorHost")


def make_bartender_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Bartender")


def make_security_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SecurityOfficer")
