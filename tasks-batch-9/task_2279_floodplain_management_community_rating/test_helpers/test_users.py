"""Pre-built role headers for every role named by the PRD.

Every request must carry X-User-ID, identifying the acting user, and
X-User-Role, naming the role that user is acting in.

Three roles carry an opaque operator identifier not tied to any persisted
entity, so the shared constants below are always correct for them.  The
PropertyOwner role alone is entity-backed: X-User-ID is the id of the acting
Property, so ownership-gated calls MUST use make_property_owner_headers()
with the real Property id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — correct for the three opaque roles, and usable for the
# PropertyOwner only in tests that do not exercise an ownership check.
TEST_USERS = {
    "coordinator_headers": build_user_headers("snc-01", "StateNfipCoordinator"),
    "coordinator_alt_headers": build_user_headers("snc-02", "StateNfipCoordinator"),
    "administrator_headers": build_user_headers("fpa-01", "FloodplainAdministrator"),
    "administrator_alt_headers": build_user_headers("fpa-02", "FloodplainAdministrator"),
    "appeals_board_headers": build_user_headers("abm-01", "AppealsBoardMember"),
    "appeals_board_alt_headers": build_user_headers("abm-02", "AppealsBoardMember"),
    # Fallback only: never equals a real Property id, so ownership checks reject it.
    "property_owner_headers": build_user_headers("owner-not-a-property", "PropertyOwner"),
}


def make_property_owner_headers(property_id: str) -> dict:
    """Headers for the PropertyOwner of `property_id`.

    The PropertyOwner role is entity-backed: pass the acting Property's id so
    that ownership checks comparing the resource's foreign key to X-User-ID
    succeed.
    """
    return build_user_headers(property_id, "PropertyOwner")


def make_coordinator_headers(user_id: str) -> dict:
    """Headers for a StateNfipCoordinator with a specific operator identifier."""
    return build_user_headers(user_id, "StateNfipCoordinator")


def make_administrator_headers(user_id: str) -> dict:
    """Headers for a FloodplainAdministrator with a specific operator identifier.

    Use this when a test needs the identifier the server records in
    determined_by_user_id to be a known value.
    """
    return build_user_headers(user_id, "FloodplainAdministrator")


def make_appeals_board_headers(user_id: str) -> dict:
    """Headers for an AppealsBoardMember with a specific operator identifier.

    Use this to drive (or to avoid) the segregation-of-duties comparison
    against determined_by_user_id.
    """
    return build_user_headers(user_id, "AppealsBoardMember")


ALL_ROLE_NAMES = [
    "StateNfipCoordinator",
    "FloodplainAdministrator",
    "PropertyOwner",
    "AppealsBoardMember",
]
