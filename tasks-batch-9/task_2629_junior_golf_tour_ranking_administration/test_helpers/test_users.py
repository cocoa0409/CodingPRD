"""Caller identities and the header builders that thread them.

For a `Member` caller the `X-User-ID` is the id of the acting Member row, so those
headers must be built per instance. For the other six roles the id is an opaque
operator identifier that is never compared to any entity id, so fixed literals are
sufficient and are reused by the officiating stamps the API records.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import (
    ROLE_ANONYMOUS,
    ROLE_CHIEF_REFEREE,
    ROLE_COACH,
    ROLE_CONDUCT_COMMITTEE,
    ROLE_MEMBER,
    ROLE_RULES_OFFICIAL,
    ROLE_TOUR_ADMIN,
)

# Opaque operator identifiers
TOUR_ADMIN_USER_ID = "admin-1"
RULES_OFFICIAL_USER_ID = "official-anna"
SECOND_RULES_OFFICIAL_USER_ID = "official-bo"
CHIEF_REFEREE_USER_ID = "referee-nolan"
SECOND_CHIEF_REFEREE_USER_ID = "referee-pia"
CONDUCT_COMMITTEE_USER_ID = "cc-1"
COACH_USER_ID = "coach-recruit-1"
SECOND_COACH_USER_ID = "coach-recruit-2"
ANONYMOUS_USER_ID = "anon-1"

TOUR_ADMIN = build_user_headers(TOUR_ADMIN_USER_ID, ROLE_TOUR_ADMIN)
RULES_OFFICIAL = build_user_headers(RULES_OFFICIAL_USER_ID, ROLE_RULES_OFFICIAL)
SECOND_RULES_OFFICIAL = build_user_headers(
    SECOND_RULES_OFFICIAL_USER_ID, ROLE_RULES_OFFICIAL
)
CHIEF_REFEREE = build_user_headers(CHIEF_REFEREE_USER_ID, ROLE_CHIEF_REFEREE)
SECOND_CHIEF_REFEREE = build_user_headers(
    SECOND_CHIEF_REFEREE_USER_ID, ROLE_CHIEF_REFEREE
)
CONDUCT_COMMITTEE = build_user_headers(CONDUCT_COMMITTEE_USER_ID, ROLE_CONDUCT_COMMITTEE)
COACH = build_user_headers(COACH_USER_ID, ROLE_COACH)
SECOND_COACH = build_user_headers(SECOND_COACH_USER_ID, ROLE_COACH)
ANONYMOUS = build_user_headers(ANONYMOUS_USER_ID, ROLE_ANONYMOUS)

# A request with no role header at all.
NO_ROLE_HEADERS = {"X-User-ID": "nobody-1"}


def member_headers(member_id):
    """Headers for a junior acting on their own rows."""
    return build_user_headers(str(member_id), ROLE_MEMBER)


def rules_official_headers(user_id):
    """A named officiating identity, for segregation-of-duties scenarios."""
    return build_user_headers(str(user_id), ROLE_RULES_OFFICIAL)


def chief_referee_headers(user_id):
    return build_user_headers(str(user_id), ROLE_CHIEF_REFEREE)


def coach_headers(user_id):
    return build_user_headers(str(user_id), ROLE_COACH)


def unknown_role_headers(role_name="Spectator"):
    """Headers naming a role the specification never declares."""
    return build_user_headers("stranger-1", role_name)
