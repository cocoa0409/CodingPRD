"""Actor header builders.

Four roles -- CommunityManager, InsuranceAdjuster, AssociationAttorney and
TitleAgent -- are opaque: any stable, non-empty X-User-ID is accepted, so a
module-level constant header dict is enough.

Three roles -- BoardDirector, BoardTreasurer and UnitOwner -- are entity-backed
on UnitOwner: the X-User-ID must resolve to a UnitOwner row of the association
being acted on, and for the two board roles that row must additionally be
seated with a board_role other than NONE.  Those roles therefore have no usable
module-level constant; callers must build headers from a real owner id with the
``make_*`` helpers below.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ASSOCIATION_ATTORNEY,
    ROLE_BOARD_DIRECTOR,
    ROLE_BOARD_TREASURER,
    ROLE_COMMUNITY_MANAGER,
    ROLE_INSURANCE_ADJUSTER,
    ROLE_TITLE_AGENT,
    ROLE_UNIT_OWNER,
)

# ----------------------------------------------------------------------
# Opaque-identity actors
# ----------------------------------------------------------------------
MANAGER_USER_ID = "mgr-0001"
ADJUSTER_USER_ID = "adj-0001"
ATTORNEY_USER_ID = "atty-0001"
TITLE_AGENT_USER_ID = "title-0001"

MANAGER_HEADERS = build_user_headers(MANAGER_USER_ID, ROLE_COMMUNITY_MANAGER)
ADJUSTER_HEADERS = build_user_headers(ADJUSTER_USER_ID, ROLE_INSURANCE_ADJUSTER)
ATTORNEY_HEADERS = build_user_headers(ATTORNEY_USER_ID, ROLE_ASSOCIATION_ATTORNEY)
TITLE_AGENT_HEADERS = build_user_headers(TITLE_AGENT_USER_ID, ROLE_TITLE_AGENT)

OPAQUE_ROLE_HEADERS = {
    ROLE_COMMUNITY_MANAGER: MANAGER_HEADERS,
    ROLE_INSURANCE_ADJUSTER: ADJUSTER_HEADERS,
    ROLE_ASSOCIATION_ATTORNEY: ATTORNEY_HEADERS,
    ROLE_TITLE_AGENT: TITLE_AGENT_HEADERS,
}


# ----------------------------------------------------------------------
# Entity-backed actors -- always built from a real UnitOwner id
# ----------------------------------------------------------------------
def make_director_headers(owner_id: str) -> dict[str, str]:
    """Headers for a seated director acting as BoardDirector."""
    return build_user_headers(owner_id, ROLE_BOARD_DIRECTOR)


def make_treasurer_headers(owner_id: str) -> dict[str, str]:
    """Headers for a seated treasurer acting as BoardTreasurer."""
    return build_user_headers(owner_id, ROLE_BOARD_TREASURER)


def make_owner_headers(owner_id: str) -> dict[str, str]:
    """Headers for a unit owner of record acting as UnitOwner."""
    return build_user_headers(owner_id, ROLE_UNIT_OWNER)


def make_headers(role: str, user_id: str) -> dict[str, str]:
    """Headers for an arbitrary role/user pair."""
    return build_user_headers(user_id, role)


# ----------------------------------------------------------------------
# Malformed identity probes
# ----------------------------------------------------------------------
#: No X-User-ID and no X-User-Role at all.
NO_AUTH_HEADERS: dict[str, str] = {"Content-Type": "application/json"}

#: A role header naming something outside the PRD's seven roles.
UNKNOWN_ROLE_HEADERS = build_user_headers("ghost-0001", "NotARole")

#: Role header present, identity header absent.
MISSING_USER_ID_HEADERS = {
    "X-User-Role": ROLE_COMMUNITY_MANAGER,
    "Content-Type": "application/json",
}

#: Identity header present, role header absent.
MISSING_ROLE_HEADERS = {
    "X-User-ID": MANAGER_USER_ID,
    "Content-Type": "application/json",
}
