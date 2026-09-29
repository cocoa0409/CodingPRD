"""Shared caller identities.

The API authenticates nothing: it reads ``X-User-ID`` and ``X-User-Role`` and
trusts them.  Four of the six roles are opaque — any non-empty identifier works
— so this module pins one stable identifier per role and every test reuses it.

The two committee roles are different: for ``CommitteeChair`` and
``CommitteeMember`` the ``X-User-ID`` must resolve to a committee member row on
the plan being acted on, so those headers can only be built once the member has
been appointed.  Use :func:`member_headers` / :func:`chair_headers` with the
real member id for those.
"""

from typing import Optional

from prd_bench_local_runner.testing import build_user_headers

from .types import Headers, Role


class TestUsers:
    """Stable identifiers for the roles that are not entity-backed."""

    PLAN_SPONSOR_ADMIN = "psa-ops"
    INVESTMENT_CONSULTANT = "ic-1"
    RECORDKEEPER = "rk-1"
    PLAN_AUDITOR = "aud-1"

    #: A second sponsor administrator, for tests that need two distinct actors
    #: in the same non-entity-backed role.
    PLAN_SPONSOR_ADMIN_ALT = "psa-ops-2"
    INVESTMENT_CONSULTANT_ALT = "ic-2"

    #: An identifier that is syntactically fine but matches no committee member.
    UNKNOWN_ACTOR = "not-a-member"


#: Backwards-compatible alias — some tests read the mapping form.
TEST_USERS = {
    Role.PLAN_SPONSOR_ADMIN: TestUsers.PLAN_SPONSOR_ADMIN,
    Role.INVESTMENT_CONSULTANT: TestUsers.INVESTMENT_CONSULTANT,
    Role.RECORDKEEPER: TestUsers.RECORDKEEPER,
    Role.PLAN_AUDITOR: TestUsers.PLAN_AUDITOR,
}


# --------------------------------------------------------------------------
# Ready-made headers for the opaque roles
# --------------------------------------------------------------------------


def sponsor_headers(user_id: Optional[str] = None) -> Headers:
    return build_user_headers(user_id or TestUsers.PLAN_SPONSOR_ADMIN, Role.PLAN_SPONSOR_ADMIN)


def consultant_headers(user_id: Optional[str] = None) -> Headers:
    return build_user_headers(
        user_id or TestUsers.INVESTMENT_CONSULTANT, Role.INVESTMENT_CONSULTANT
    )


def recordkeeper_headers(user_id: Optional[str] = None) -> Headers:
    return build_user_headers(user_id or TestUsers.RECORDKEEPER, Role.RECORDKEEPER)


def auditor_headers(user_id: Optional[str] = None) -> Headers:
    return build_user_headers(user_id or TestUsers.PLAN_AUDITOR, Role.PLAN_AUDITOR)


# --------------------------------------------------------------------------
# Entity-backed headers
# --------------------------------------------------------------------------


def member_headers(member_id: str) -> Headers:
    """Act as the committee member whose row id is ``member_id``."""
    return build_user_headers(member_id, Role.COMMITTEE_MEMBER)


def chair_headers(member_id: str) -> Headers:
    """Act as the chair; ``member_id`` must be the member seated in the chair
    seat."""
    return build_user_headers(member_id, Role.COMMITTEE_CHAIR)


#: Explicit aliases, for readability at call sites that emphasise the seat.
make_committee_member_headers = member_headers
make_committee_chair_headers = chair_headers


def headers_for_role(role: str, user_id: Optional[str] = None) -> Headers:
    """Build headers for any role.  Entity-backed roles require ``user_id``."""
    if role in Role.ENTITY_BACKED:
        assert user_id, f"{role} needs a real committee member id"
        return build_user_headers(user_id, role)
    default = TEST_USERS.get(role)
    assert default or user_id, f"unknown role {role}"
    return build_user_headers(user_id or default, role)


def other_roles(*allowed: str) -> tuple:
    """The roles that are *not* in ``allowed`` — the candidates for a rejection
    check."""
    return tuple(role for role in Role.ALL if role not in allowed)


__all__ = [
    "TestUsers",
    "TEST_USERS",
    "sponsor_headers",
    "consultant_headers",
    "recordkeeper_headers",
    "auditor_headers",
    "member_headers",
    "chair_headers",
    "make_committee_member_headers",
    "make_committee_chair_headers",
    "headers_for_role",
    "other_roles",
]
