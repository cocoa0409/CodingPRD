"""Canonical test identities and header builders (PRD 2.1).

Both X-User-ID and X-User-Role are mandatory on every request. The nine roles
are peers; X-User-ID is never compared against a resource id except at the two
segregation-of-duties gates of PRD 2.10, which is why several roles carry a
second, distinct identity for two-person-rule scenarios.
"""

from prd_bench_local_runner.testing.headers import build_user_headers

from .types import UserRole

TEST_USERS = {
    UserRole.STATION_ADMIN: {"user_id": "sa-alpha", "role": UserRole.STATION_ADMIN},
    UserRole.OUTAGE_DIRECTOR: {"user_id": "od-alpha", "role": UserRole.OUTAGE_DIRECTOR},
    UserRole.OUTAGE_PLANNER: {"user_id": "op-alpha", "role": UserRole.OUTAGE_PLANNER},
    UserRole.REACTOR_ENGINEER: {"user_id": "re-alpha", "role": UserRole.REACTOR_ENGINEER},
    UserRole.CONTRACTOR_COORDINATOR: {
        "user_id": "cc-alpha",
        "role": UserRole.CONTRACTOR_COORDINATOR,
    },
    UserRole.ACCESS_AUTHORITY: {"user_id": "aa-alpha", "role": UserRole.ACCESS_AUTHORITY},
    UserRole.RAD_PROTECTION_PLANNER: {
        "user_id": "rpp-alpha",
        "role": UserRole.RAD_PROTECTION_PLANNER,
    },
    UserRole.RAD_PROTECTION_MANAGER: {
        "user_id": "rpm-alpha",
        "role": UserRole.RAD_PROTECTION_MANAGER,
    },
    UserRole.REGULATORY_AFFAIRS: {"user_id": "ra-alpha", "role": UserRole.REGULATORY_AFFAIRS},
}

# Second identities, used only where PRD 2.10 requires a different acting user.
SECOND_USERS = {
    UserRole.OUTAGE_DIRECTOR: "od-beta",
    UserRole.REACTOR_ENGINEER: "re-beta",
    UserRole.REGULATORY_AFFAIRS: "ra-beta",
}


def _headers(role: str, user_id=None):
    return build_user_headers(user_id or TEST_USERS[role]["user_id"], role)


def make_station_admin_headers(user_id=None):
    return _headers(UserRole.STATION_ADMIN, user_id)


def make_outage_director_headers(user_id=None):
    return _headers(UserRole.OUTAGE_DIRECTOR, user_id)


def make_outage_planner_headers(user_id=None):
    return _headers(UserRole.OUTAGE_PLANNER, user_id)


def make_reactor_engineer_headers(user_id=None):
    return _headers(UserRole.REACTOR_ENGINEER, user_id)


def make_contractor_coordinator_headers(user_id=None):
    return _headers(UserRole.CONTRACTOR_COORDINATOR, user_id)


def make_access_authority_headers(user_id=None):
    return _headers(UserRole.ACCESS_AUTHORITY, user_id)


def make_rad_protection_planner_headers(user_id=None):
    return _headers(UserRole.RAD_PROTECTION_PLANNER, user_id)


def make_rad_protection_manager_headers(user_id=None):
    return _headers(UserRole.RAD_PROTECTION_MANAGER, user_id)


def make_regulatory_affairs_headers(user_id=None):
    return _headers(UserRole.REGULATORY_AFFAIRS, user_id)


def make_headers_for_role(role: str, user_id=None):
    """Headers for any of the nine roles named in PRD 2.1."""
    return _headers(role, user_id)


def make_headers_with_unknown_role(user_id: str = "ghost-1"):
    """An X-User-Role the PRD does not enumerate --- PRD 2.1 treats an
    unrecognised role exactly like a missing header."""
    return build_user_headers(user_id, "ReactorOperatorTrainee")
