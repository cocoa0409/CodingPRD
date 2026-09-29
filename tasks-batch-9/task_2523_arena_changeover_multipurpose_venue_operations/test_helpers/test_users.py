"""Pre-built role headers for every role named in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    BOOKING_MANAGER_USER_ID,
    DIRECTOR_USER_ID,
    LABOR_COORDINATOR_USER_ID,
    SECOND_SUPERVISOR_USER_ID,
    SUPERVISOR_USER_ID,
)

# Shared constants.  Safe for the four roles whose X-User-ID is an opaque
# operator identifier the server never compares to any entity id, and for
# tests that do not exercise anchor-tenant ownership.
TEST_USERS = {
    "director_headers": build_user_headers(
        DIRECTOR_USER_ID, "VenueOperationsDirector"
    ),
    "second_director_headers": build_user_headers(
        "dir-second", "VenueOperationsDirector"
    ),
    "booking_manager_headers": build_user_headers(
        BOOKING_MANAGER_USER_ID, "BookingManager"
    ),
    "changeover_supervisor_headers": build_user_headers(
        SUPERVISOR_USER_ID, "ChangeoverSupervisor"
    ),
    "second_supervisor_headers": build_user_headers(
        SECOND_SUPERVISOR_USER_ID, "ChangeoverSupervisor"
    ),
    "labor_coordinator_headers": build_user_headers(
        LABOR_COORDINATOR_USER_ID, "LaborCoordinator"
    ),
    # AnchorTenantRep is the one entity-backed role: this shared constant is a
    # fallback for tests that never reach an ownership check.
    "anchor_tenant_rep_headers": build_user_headers(
        "tenant-rep-unbound", "AnchorTenantRep"
    ),
}


def make_director_headers(user_id: str) -> dict:
    """Headers for a VenueOperationsDirector acting under a chosen operator id.

    The identifier is opaque, but sign-off compares it against the order's
    opened_by_user_id, so tests need to be able to choose it.
    """
    return build_user_headers(user_id, "VenueOperationsDirector")


def make_booking_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BookingManager")


def make_changeover_supervisor_headers(user_id: str) -> dict:
    """Headers for a ChangeoverSupervisor; the id is recorded as opened_by_user_id."""
    return build_user_headers(user_id, "ChangeoverSupervisor")


def make_labor_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LaborCoordinator")


def make_anchor_tenant_rep_headers(tenant_id: str) -> dict:
    """Headers for an AnchorTenantRep.

    X-User-ID is the id of the acting anchor tenant, so ownership-gated calls
    MUST pass the real tenant id here.
    """
    return build_user_headers(tenant_id, "AnchorTenantRep")


ALL_ROLE_NAMES = [
    "VenueOperationsDirector",
    "BookingManager",
    "ChangeoverSupervisor",
    "LaborCoordinator",
    "AnchorTenantRep",
]
