"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

    "All five roles are entity-backed by Member. When X-User-Role is
    Member, X-User-ID is the id of the acting Member; ownership checks
    on any resource that references a Member ... compare the resource's
    foreign-key field to X-User-ID. The same identity rule applies to
    SecretaryRole, TreasurerRole, PresidentRole, and DirectorRole:
    X-User-ID is the id of the Member who currently holds that board
    seat (verified against Member.board_role)."

Every role is entity-backed. The shared *_headers constants below use
deterministic seed strings; they are appropriate ONLY for tests whose
success does not depend on the caller owning the subject resource — for
example, ERR_UNAUTHENTICATED probes that send empty/malformed values
or ERR_FORBIDDEN probes that simply test "role X cannot call endpoint Y"
without needing the caller to own the target.

The mandatory builders are make_<role>_headers(member_id). Fixtures
that create a Member and then act as that Member MUST mint headers
with that Member.id rather than reusing the shared constant — otherwise
the server's ownership check (e.g., Payment.member_id == X-User-ID,
ACCRequest.submitted_by_member_id == X-User-ID, Ballot.voter_member_id
== X-User-ID) would reject the call.

A practical note for board roles: the PresidentRole is the bootstrap
operator (the sole creator of Members, Units, elections, and the clock-
advance driver). Implementations must accept a President without an
existing Member record at first call. Tests use PRESIDENT_BOOTSTRAP_ID
for this purpose until an election certifies a real Member into the
PRESIDENT seat. The fixture layer then switches to
make_president_role_headers(elected_member_id) when ownership of the
seat is load-bearing for the test.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Bootstrap identifiers — used by President-only roster ops that must
# precede any Member.create call.
# ---------------------------------------------------------------------------
PRESIDENT_BOOTSTRAP_ID: str = "president-bootstrap-0001"
TREASURER_BOOTSTRAP_ID: str = "treasurer-bootstrap-0001"
SECRETARY_BOOTSTRAP_ID: str = "secretary-bootstrap-0001"
DIRECTOR_BOOTSTRAP_ID: str = "director-bootstrap-0001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # All five roles are entity_backed:Member per PRD §2.1.
    # These shared constants are intended for non-ownership tests only
    # (auth probes, role-forbidden probes, 404 probes).
    "member_headers": build_user_headers("member-shared-0001", "Member"),
    "secretary_role_headers": build_user_headers(
        SECRETARY_BOOTSTRAP_ID, "SecretaryRole",
    ),
    "treasurer_role_headers": build_user_headers(
        TREASURER_BOOTSTRAP_ID, "TreasurerRole",
    ),
    "president_role_headers": build_user_headers(
        PRESIDENT_BOOTSTRAP_ID, "PresidentRole",
    ),
    "director_role_headers": build_user_headers(
        DIRECTOR_BOOTSTRAP_ID, "DirectorRole",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — MANDATORY for entity_backed:Member roles
# whenever the downstream call is ownership-gated.
#
# PRD §2.1: "ownership checks on any resource that references a Member ...
# compare the resource's foreign-key field to X-User-ID."
# ---------------------------------------------------------------------------
def make_member_headers(member_id: str) -> Dict[str, str]:
    """Headers for a specific Member. Use this whenever the call is
    gated on Payment.member_id, ACCRequest.submitted_by_member_id,
    Candidate.member_id, Ballot.voter_member_id, or any DELETE/PATCH
    whose owner is compared to X-User-ID.
    """
    return build_user_headers(member_id, "Member")


def make_secretary_role_headers(member_id: str) -> Dict[str, str]:
    """Headers for a SecretaryRole identified by a real Member.id.

    PRD §2.1: "X-User-ID is the id of the Member who currently holds
    that board seat (verified against Member.board_role)."

    Use after a Member has been certified into the SECRETARY board seat;
    or, for fixtures that simply need to invoke a Secretary-exclusive
    endpoint on a payload whose acceptance does NOT depend on the seat
    holder's identity, the shared constant in TEST_USERS may be used.
    """
    return build_user_headers(member_id, "SecretaryRole")


def make_treasurer_role_headers(member_id: str) -> Dict[str, str]:
    """Headers for a TreasurerRole identified by a real Member.id."""
    return build_user_headers(member_id, "TreasurerRole")


def make_president_role_headers(member_id: str) -> Dict[str, str]:
    """Headers for a PresidentRole identified by a real Member.id."""
    return build_user_headers(member_id, "PresidentRole")


def make_director_role_headers(member_id: str) -> Dict[str, str]:
    """Headers for a DirectorRole identified by a real Member.id."""
    return build_user_headers(member_id, "DirectorRole")


__all__ = [
    "PRESIDENT_BOOTSTRAP_ID",
    "TREASURER_BOOTSTRAP_ID",
    "SECRETARY_BOOTSTRAP_ID",
    "DIRECTOR_BOOTSTRAP_ID",
    "TEST_USERS",
    "make_member_headers",
    "make_secretary_role_headers",
    "make_treasurer_role_headers",
    "make_president_role_headers",
    "make_director_role_headers",
]
