"""Canonical acting principals and per-role header builders.

Six of the eight roles act under an opaque operator identifier that the server
never compares against any stored row; those get a fixed identifier here so
that tests can assert the stamped-identity fields (``proposed_by_user_id``,
``flagged_by_user_id``, ``decided_by_user_id`` and friends) by value.

Two roles are entity-backed and therefore cannot have a fixed identifier:
``Agent`` carries the id of the acting Agent row and ``PartnerRep`` carries the
id of the acting OutsourcePartner row.  Those two are built per-call from the
row the test just created.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_AGENT,
    ROLE_CAPACITY_PLANNER,
    ROLE_INTRADAY_CONTROLLER,
    ROLE_PARTNER_REP,
    ROLE_SCHEDULING_MANAGER,
    ROLE_SOURCING_MANAGER,
    ROLE_TEAM_COACH,
    ROLE_WORKFORCE_ANALYST,
)

# ─── Opaque operator identifiers ──────────────────────

PLANNER_USER_ID = "u-planner-1"
PLANNER_ALT_USER_ID = "u-planner-2"
ANALYST_USER_ID = "u-analyst-1"
ANALYST_ALT_USER_ID = "u-analyst-2"
SCHEDULER_USER_ID = "u-sched-1"
SCHEDULER_ALT_USER_ID = "u-sched-2"
INTRADAY_USER_ID = "u-intraday-1"
INTRADAY_ALT_USER_ID = "u-intraday-2"
COACH_USER_ID = "u-coach-1"
COACH_ALT_USER_ID = "u-coach-2"
SOURCING_USER_ID = "u-src-1"
SOURCING_ALT_USER_ID = "u-src-2"

TEST_USERS = {
    ROLE_CAPACITY_PLANNER: {
        "user_id": PLANNER_USER_ID,
        "role": ROLE_CAPACITY_PLANNER,
        "identity": "opaque",
    },
    ROLE_WORKFORCE_ANALYST: {
        "user_id": ANALYST_USER_ID,
        "role": ROLE_WORKFORCE_ANALYST,
        "identity": "opaque",
    },
    ROLE_SCHEDULING_MANAGER: {
        "user_id": SCHEDULER_USER_ID,
        "role": ROLE_SCHEDULING_MANAGER,
        "identity": "opaque",
    },
    ROLE_INTRADAY_CONTROLLER: {
        "user_id": INTRADAY_USER_ID,
        "role": ROLE_INTRADAY_CONTROLLER,
        "identity": "opaque",
    },
    ROLE_TEAM_COACH: {
        "user_id": COACH_USER_ID,
        "role": ROLE_TEAM_COACH,
        "identity": "opaque",
    },
    ROLE_SOURCING_MANAGER: {
        "user_id": SOURCING_USER_ID,
        "role": ROLE_SOURCING_MANAGER,
        "identity": "opaque",
    },
    ROLE_AGENT: {
        "user_id": None,
        "role": ROLE_AGENT,
        "identity": "entity_backed:Agent",
    },
    ROLE_PARTNER_REP: {
        "user_id": None,
        "role": ROLE_PARTNER_REP,
        "identity": "entity_backed:OutsourcePartner",
    },
}


# ─── Opaque-role header builders ──────────────────────

def make_planner_headers(user_id=PLANNER_USER_ID):
    """Headers for a CapacityPlanner acting under an opaque operator id."""
    return build_user_headers(user_id, ROLE_CAPACITY_PLANNER)


def make_analyst_headers(user_id=ANALYST_USER_ID):
    """Headers for a WorkforceAnalyst acting under an opaque operator id."""
    return build_user_headers(user_id, ROLE_WORKFORCE_ANALYST)


def make_scheduler_headers(user_id=SCHEDULER_USER_ID):
    """Headers for a SchedulingManager acting under an opaque operator id."""
    return build_user_headers(user_id, ROLE_SCHEDULING_MANAGER)


def make_intraday_headers(user_id=INTRADAY_USER_ID):
    """Headers for an IntradayController acting under an opaque operator id."""
    return build_user_headers(user_id, ROLE_INTRADAY_CONTROLLER)


def make_coach_headers(user_id=COACH_USER_ID):
    """Headers for a TeamCoach acting under an opaque operator id."""
    return build_user_headers(user_id, ROLE_TEAM_COACH)


def make_sourcing_headers(user_id=SOURCING_USER_ID):
    """Headers for a SourcingManager acting under an opaque operator id."""
    return build_user_headers(user_id, ROLE_SOURCING_MANAGER)


# ─── Entity-backed role header builders ───────────────

def make_agent_headers(agent_id):
    """Headers for the Agent role: X-User-ID is the acting Agent row's id."""
    return build_user_headers(agent_id, ROLE_AGENT)


def make_partner_rep_headers(outsource_partner_id):
    """Headers for the PartnerRep role: X-User-ID is the partner row's id."""
    return build_user_headers(outsource_partner_id, ROLE_PARTNER_REP)


# ─── Convenience: prebuilt opaque-role header dicts ───

PLANNER_HEADERS = make_planner_headers()
ANALYST_HEADERS = make_analyst_headers()
SCHEDULER_HEADERS = make_scheduler_headers()
INTRADAY_HEADERS = make_intraday_headers()
COACH_HEADERS = make_coach_headers()
SOURCING_HEADERS = make_sourcing_headers()

ALL_OPAQUE_ROLE_HEADERS = {
    ROLE_CAPACITY_PLANNER: PLANNER_HEADERS,
    ROLE_WORKFORCE_ANALYST: ANALYST_HEADERS,
    ROLE_SCHEDULING_MANAGER: SCHEDULER_HEADERS,
    ROLE_INTRADAY_CONTROLLER: INTRADAY_HEADERS,
    ROLE_TEAM_COACH: COACH_HEADERS,
    ROLE_SOURCING_MANAGER: SOURCING_HEADERS,
}
