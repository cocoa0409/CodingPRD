"""Pre-built role headers for every role in the PRD (§2.1).

The four operator roles (GardenAdmin, GardenStaff, RentalCoordinator,
DevelopmentOfficer) have OPAQUE identity — X-User-ID is never compared to any
entity id — so the shared constants below are the canonical form for those roles.

Visitor is an entity_backed:Membership role: when a Visitor performs an
ownership-gated mutation (reservation cancel, membership renew/cancel/reinstate,
registration withdraw, rental cancel) the server compares X-User-ID to the
owning Membership.id. Such calls MUST use make_visitor_headers(membership_id)
with the real membership id; the shared visitor constant is only safe for
non-ownership calls (create, or operations on non-member resources).
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ADMIN_USER_ID,
    STAFF_USER_ID,
    RENTAL_COORDINATOR_USER_ID,
    DEVELOPMENT_OFFICER_USER_ID,
    ANON_VISITOR_USER_ID,
)


# Shared constants — canonical for opaque operator roles; visitor constant is a
# fallback for non-ownership-gated visitor calls only.
TEST_USERS = {
    "admin_headers": build_user_headers(ADMIN_USER_ID, "GardenAdmin"),
    "staff_headers": build_user_headers(STAFF_USER_ID, "GardenStaff"),
    "rental_coordinator_headers": build_user_headers(RENTAL_COORDINATOR_USER_ID, "RentalCoordinator"),
    "development_officer_headers": build_user_headers(DEVELOPMENT_OFFICER_USER_ID, "DevelopmentOfficer"),
    "visitor_headers": build_user_headers(ANON_VISITOR_USER_ID, "Visitor"),
}


def make_visitor_headers(user_id: str) -> dict:
    """Visitor (entity_backed:Membership) headers for a specific membership id.
    Pass the owning Membership.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Visitor")


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "GardenAdmin")


def make_staff_headers(user_id: str = STAFF_USER_ID) -> dict:
    return build_user_headers(user_id, "GardenStaff")


def make_rental_coordinator_headers(user_id: str = RENTAL_COORDINATOR_USER_ID) -> dict:
    return build_user_headers(user_id, "RentalCoordinator")


def make_development_officer_headers(user_id: str = DEVELOPMENT_OFFICER_USER_ID) -> dict:
    return build_user_headers(user_id, "DevelopmentOfficer")
