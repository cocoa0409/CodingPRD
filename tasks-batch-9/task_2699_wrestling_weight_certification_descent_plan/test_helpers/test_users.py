"""
Identity headers.

Every request carries ``X-User-ID`` and ``X-User-Role``.  Two of the five roles
are entity-backed: an ``Assessor`` caller's user id is the id of the assessor row
it acts as, and a ``TeamCoach`` caller's user id is the id of the team it
coaches, which is what ownership checks compare against.  The remaining three
roles — ``StateOffice``, ``WeighInOfficial`` and ``MedicalReviewer`` — are opaque
principals with no backing row, so any stable identifier works for them.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ASSESSOR,
    ROLE_MEDICAL_REVIEWER,
    ROLE_STATE_OFFICE,
    ROLE_TEAM_COACH,
    ROLE_WEIGH_IN_OFFICIAL,
)

# Opaque principals: stable identifiers for the three roles with no backing row.
STATE_OFFICE_USER_ID = "11111111-1111-4111-8111-111111111111"
WEIGH_IN_OFFICIAL_USER_ID = "22222222-2222-4222-8222-222222222222"
SECOND_WEIGH_IN_OFFICIAL_USER_ID = "22222222-2222-4222-8222-222222222223"
MEDICAL_REVIEWER_USER_ID = "33333333-3333-4333-8333-333333333333"
SECOND_MEDICAL_REVIEWER_USER_ID = "33333333-3333-4333-8333-333333333334"

# A syntactically valid identifier that matches no stored row.
UNKNOWN_USER_ID = "44444444-4444-4444-8444-444444444444"


# ── The three opaque roles ───────────────────────────────────────────

STATE_OFFICE = build_user_headers(STATE_OFFICE_USER_ID, ROLE_STATE_OFFICE)
WEIGH_IN_OFFICIAL = build_user_headers(WEIGH_IN_OFFICIAL_USER_ID, ROLE_WEIGH_IN_OFFICIAL)
SECOND_WEIGH_IN_OFFICIAL = build_user_headers(
    SECOND_WEIGH_IN_OFFICIAL_USER_ID, ROLE_WEIGH_IN_OFFICIAL
)
MEDICAL_REVIEWER = build_user_headers(MEDICAL_REVIEWER_USER_ID, ROLE_MEDICAL_REVIEWER)
SECOND_MEDICAL_REVIEWER = build_user_headers(
    SECOND_MEDICAL_REVIEWER_USER_ID, ROLE_MEDICAL_REVIEWER
)


# ── The two entity-backed roles ──────────────────────────────────────

def assessor_headers(assessor_id: str) -> Dict[str, str]:
    """Act as the assessor whose row id is ``assessor_id``."""
    return build_user_headers(assessor_id, ROLE_ASSESSOR)


def coach_headers(team_id: str) -> Dict[str, str]:
    """Act as the coach of the team whose row id is ``team_id``."""
    return build_user_headers(team_id, ROLE_TEAM_COACH)


def headers_for_role(role: str, user_id: str) -> Dict[str, str]:
    """Build headers for an arbitrary role and identifier pair."""
    return build_user_headers(user_id, role)


def opaque_headers_for_role(role: str) -> Dict[str, str]:
    """Headers for a role that needs no backing row, for authorisation probes.

    The two entity-backed roles get a syntactically valid identifier that
    resolves to nothing, which is enough to exercise a role check that runs
    before any row lookup.
    """
    known = {
        ROLE_STATE_OFFICE: STATE_OFFICE,
        ROLE_WEIGH_IN_OFFICIAL: WEIGH_IN_OFFICIAL,
        ROLE_MEDICAL_REVIEWER: MEDICAL_REVIEWER,
    }
    if role in known:
        return dict(known[role])
    return build_user_headers(UNKNOWN_USER_ID, role)


# ── Malformed identity, for the authentication gate ──────────────────

NO_HEADERS: Dict[str, str] = {}

MISSING_USER_ID = {"X-User-Role": ROLE_STATE_OFFICE}

MISSING_ROLE = {"X-User-ID": STATE_OFFICE_USER_ID}

UNKNOWN_ROLE = {
    "X-User-ID": STATE_OFFICE_USER_ID,
    "X-User-Role": "LeagueCommissioner",
}

EMPTY_USER_ID = {"X-User-ID": "", "X-User-Role": ROLE_STATE_OFFICE}

EMPTY_ROLE = {"X-User-ID": STATE_OFFICE_USER_ID, "X-User-Role": ""}

# Every way an identity can fail to be established, for parametrised probes.
INVALID_IDENTITY_HEADERS = [
    ("no headers at all", NO_HEADERS),
    ("missing user id", MISSING_USER_ID),
    ("missing role", MISSING_ROLE),
    ("unknown role name", UNKNOWN_ROLE),
    ("empty user id", EMPTY_USER_ID),
    ("empty role", EMPTY_ROLE),
]
