"""Pre-built role headers for every role named in PRD section 2.1.

`ClubAdmin` identity is opaque: PRD 2.1 says "When `X-User-Role` is `ClubAdmin`,
`X-User-ID` is an opaque operator identifier not tied to any persisted entity",
so the shared constant is the canonical form for that role.

The other five roles are member-backed: their `X-User-ID` must be the `id` of the
acting `ClubMember`. Tests and fixtures therefore call the per-role builder with
a real member id whenever the call is ownership-gated or must resolve an actor.
"""

from prd_bench_local_runner.testing import build_user_headers

# The club office operator identifier used throughout the suite.
CLUB_ADMIN_USER_ID = "ops-desk-1"

# Shared constants — canonical for the opaque ClubAdmin role, and usable for the
# member-backed roles only in probes that deliberately supply an unresolvable
# actor (PRD 2.1: rejected with ERR_UNKNOWN_ACTOR).
TEST_USERS = {
    "club_admin_headers": build_user_headers(CLUB_ADMIN_USER_ID, "ClubAdmin"),
    "unknown_regatta_chair_headers": build_user_headers(
        "00000000-0000-4000-8000-0000000000ff", "RegattaChair"
    ),
}


def make_club_admin_headers(user_id: str = CLUB_ADMIN_USER_ID) -> dict:
    """For ClubAdmin. Identity is opaque and never resolved to a ClubMember."""
    return build_user_headers(user_id, "ClubAdmin")


def make_regatta_chair_headers(user_id: str) -> dict:
    """For RegattaChair (member-backed). Pass the acting ClubMember's id."""
    return build_user_headers(user_id, "RegattaChair")


def make_measurer_headers(user_id: str) -> dict:
    """For Measurer (member-backed). Pass the acting ClubMember's id; it is what
    lands in `measured_by_member_id` on every certificate the call creates."""
    return build_user_headers(user_id, "Measurer")


def make_race_officer_headers(user_id: str) -> dict:
    """For RaceOfficer (member-backed). Pass the acting ClubMember's id; it is
    what lands in `recorded_by_member_id` on every recall signal."""
    return build_user_headers(user_id, "RaceOfficer")


def make_jury_chair_headers(user_id: str) -> dict:
    """For JuryChair (member-backed). Pass the panel's `chair_member_id`."""
    return build_user_headers(user_id, "JuryChair")


def make_competitor_headers(user_id: str) -> dict:
    """For Competitor (member-backed). Pass the boat's `owner_member_id` or the
    entry's `helm_member_id`, whichever the call is gated on."""
    return build_user_headers(user_id, "Competitor")


def make_headers_without_user_id(role: str) -> dict:
    """Headers carrying only X-User-Role — for the missing-header probe."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def make_headers_without_role(user_id: str) -> dict:
    """Headers carrying only X-User-ID — for the missing-header probe."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
