"""Identity headers for every role the PRD defines.

Requests authenticate with ``X-User-ID`` and ``X-User-Role``. The
StateAdoptionOfficer role is bound to a concrete state: the officer's
``X-User-ID`` is the identifier of the ``StateProfile`` they administer, and any
attempt to touch another state's records is a scope violation. Every officer
header therefore has to be built from a live state profile identifier, which is
what :func:`make_state_adoption_officer_headers` is for.

The remaining seven roles are opaque: their ``X-User-ID`` is any stable string,
which matters only where the contract compares two actors on one workflow (the
proposer versus the reviewer of a content edit, the quoting versus the confirming
sales representative, or one committee member's ballot versus another's).
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_EDITORIAL_DIRECTOR,
    ROLE_PLATFORM_ADMIN,
    ROLE_PRICING_MANAGER,
    ROLE_PUBLIC_COMMENTER,
    ROLE_PUBLISHER_EDITOR,
    ROLE_REVIEW_COMMITTEE_MEMBER,
    ROLE_SALES_REP,
    ROLE_STATE_ADOPTION_OFFICER,
)

Headers = Dict[str, str]


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def make_platform_admin_headers(user_id: str = "admin-1") -> Headers:
    """Headers for the platform administrator."""
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_state_adoption_officer_headers(state_profile_id: str) -> Headers:
    """Headers for the adoption officer of the given state profile.

    ``state_profile_id`` must be the identifier returned by
    ``POST /state-profiles``: the officer's identity *is* their state.
    """
    return build_user_headers(state_profile_id, ROLE_STATE_ADOPTION_OFFICER)


def make_review_committee_member_headers(user_id: str = "cm-1") -> Headers:
    """Headers for one seated review committee member."""
    return build_user_headers(user_id, ROLE_REVIEW_COMMITTEE_MEMBER)


def make_publisher_editor_headers(user_id: str = "ed-1") -> Headers:
    """Headers for a publisher editor."""
    return build_user_headers(user_id, ROLE_PUBLISHER_EDITOR)


def make_editorial_director_headers(user_id: str = "dir-1") -> Headers:
    """Headers for an editorial director."""
    return build_user_headers(user_id, ROLE_EDITORIAL_DIRECTOR)


def make_pricing_manager_headers(user_id: str = "pm-1") -> Headers:
    """Headers for a pricing manager."""
    return build_user_headers(user_id, ROLE_PRICING_MANAGER)


def make_sales_rep_headers(user_id: str = "rep-1") -> Headers:
    """Headers for a sales representative."""
    return build_user_headers(user_id, ROLE_SALES_REP)


def make_public_commenter_headers(user_id: str = "pc-1") -> Headers:
    """Headers for a member of the public filing a comment."""
    return build_user_headers(user_id, ROLE_PUBLIC_COMMENTER)


def make_unauthenticated_headers() -> Headers:
    """A request carrying no identity headers at all."""
    return {"Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Ready-made identities
# ---------------------------------------------------------------------------

#: Named identities for the roles whose user identifier is opaque. The
#: StateAdoptionOfficer is deliberately absent: it can only be built once a
#: state profile exists.
TEST_USERS: Dict[str, Headers] = {
    "platform_admin_headers": make_platform_admin_headers("admin-1"),
    "publisher_editor_headers": make_publisher_editor_headers("ed-1"),
    "second_publisher_editor_headers": make_publisher_editor_headers("ed-2"),
    "editorial_director_headers": make_editorial_director_headers("dir-1"),
    "pricing_manager_headers": make_pricing_manager_headers("pm-1"),
    "sales_rep_headers": make_sales_rep_headers("rep-1"),
    "second_sales_rep_headers": make_sales_rep_headers("rep-2"),
    "committee_member_headers": make_review_committee_member_headers("cm-1"),
    "second_committee_member_headers": make_review_committee_member_headers("cm-2"),
    "third_committee_member_headers": make_review_committee_member_headers("cm-3"),
    "fourth_committee_member_headers": make_review_committee_member_headers("cm-4"),
    "public_commenter_headers": make_public_commenter_headers("pc-1"),
    "no_auth_headers": make_unauthenticated_headers(),
}

#: Four committee members, in seat order, for panels that need a quorum.
COMMITTEE_MEMBER_HEADERS = tuple(
    make_review_committee_member_headers(f"cm-{seat}") for seat in range(1, 6)
)

#: Five distinct members of the public, for stacking comments on one submission.
PUBLIC_COMMENTER_HEADERS = tuple(
    make_public_commenter_headers(f"pc-{n}") for n in range(1, 6)
)
