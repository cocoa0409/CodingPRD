"""
Authentication headers for every role.

Identity semantics differ by role.  ``FareInspector`` and ``Rider`` are
entity-backed: their ``X-User-ID`` must be the ``id`` of the acting
``Inspector`` or ``Rider`` record, so those two roles are only ever reached
through the ``make_..._headers`` factories, never through a shared constant.
The remaining four roles carry opaque operator identifiers, so pre-built
header dictionaries are safe for them.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ANALYST,
    ROLE_BOARD_MEMBER,
    ROLE_HEARING_OFFICER,
    ROLE_INSPECTOR,
    ROLE_PLANNER,
    ROLE_RIDER,
)

# ── Opaque operator identifiers ──────────────────────────────────────
PLANNER_USER_ID = "planner-001"
HEARING_OFFICER_USER_ID = "hearing-officer-001"
OTHER_HEARING_OFFICER_USER_ID = "hearing-officer-002"
BOARD_MEMBER_USER_ID = "board-member-001"
OTHER_BOARD_MEMBER_USER_ID = "board-member-002"
ANALYST_USER_ID = "equity-analyst-001"

PLANNER_HEADERS = build_user_headers(PLANNER_USER_ID, ROLE_PLANNER)
HEARING_OFFICER_HEADERS = build_user_headers(HEARING_OFFICER_USER_ID, ROLE_HEARING_OFFICER)
OTHER_HEARING_OFFICER_HEADERS = build_user_headers(
    OTHER_HEARING_OFFICER_USER_ID, ROLE_HEARING_OFFICER
)
BOARD_MEMBER_HEADERS = build_user_headers(BOARD_MEMBER_USER_ID, ROLE_BOARD_MEMBER)
OTHER_BOARD_MEMBER_HEADERS = build_user_headers(
    OTHER_BOARD_MEMBER_USER_ID, ROLE_BOARD_MEMBER
)
ANALYST_HEADERS = build_user_headers(ANALYST_USER_ID, ROLE_ANALYST)

# A stand-in identifier for the two entity-backed roles, usable only on
# endpoints that perform no ownership comparison at all (the logical clock).
UNBOUND_INSPECTOR_USER_ID = "00000000-0000-4000-8000-0000000000e1"
UNBOUND_RIDER_USER_ID = "00000000-0000-4000-8000-0000000000e2"

UNBOUND_INSPECTOR_HEADERS = build_user_headers(UNBOUND_INSPECTOR_USER_ID, ROLE_INSPECTOR)
UNBOUND_RIDER_HEADERS = build_user_headers(UNBOUND_RIDER_USER_ID, ROLE_RIDER)

TEST_USERS = {
    ROLE_PLANNER: PLANNER_HEADERS,
    ROLE_HEARING_OFFICER: HEARING_OFFICER_HEADERS,
    ROLE_BOARD_MEMBER: BOARD_MEMBER_HEADERS,
    ROLE_ANALYST: ANALYST_HEADERS,
}


# ── Header factories ─────────────────────────────────────────────────

def make_planner_headers(user_id: str = PLANNER_USER_ID) -> Dict[str, str]:
    """Headers for an EnforcementPlanner acting under an opaque operator id."""
    return build_user_headers(user_id, ROLE_PLANNER)


def make_fare_inspector_headers(inspector_id: str) -> Dict[str, str]:
    """Headers for a FareInspector; ``inspector_id`` is the Inspector record id."""
    return build_user_headers(inspector_id, ROLE_INSPECTOR)


def make_rider_headers(rider_id: str) -> Dict[str, str]:
    """Headers for a Rider; ``rider_id`` is the Rider record id."""
    return build_user_headers(rider_id, ROLE_RIDER)


def make_hearing_officer_headers(
    user_id: str = HEARING_OFFICER_USER_ID,
) -> Dict[str, str]:
    """Headers for a HearingOfficer acting under an opaque operator id."""
    return build_user_headers(user_id, ROLE_HEARING_OFFICER)


def make_board_member_headers(user_id: str = BOARD_MEMBER_USER_ID) -> Dict[str, str]:
    """Headers for an AppealsBoardMember acting under an opaque operator id."""
    return build_user_headers(user_id, ROLE_BOARD_MEMBER)


def make_analyst_headers(user_id: str = ANALYST_USER_ID) -> Dict[str, str]:
    """Headers for an EquityAnalyst acting under an opaque operator id."""
    return build_user_headers(user_id, ROLE_ANALYST)


# ── Deliberately malformed header sets ───────────────────────────────

def headers_without_role(user_id: str = PLANNER_USER_ID) -> Dict[str, str]:
    """A header set carrying no ``X-User-Role`` at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = ROLE_PLANNER) -> Dict[str, str]:
    """A header set carrying no ``X-User-ID`` at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str = ROLE_PLANNER) -> Dict[str, str]:
    """A header set whose ``X-User-ID`` is present but empty."""
    return build_user_headers("", role)


def headers_with_unknown_role(
    role: str = "FareAuditor", user_id: str = PLANNER_USER_ID
) -> Dict[str, str]:
    """A header set naming a role that is not one of the six declared roles."""
    return build_user_headers(user_id, role)
