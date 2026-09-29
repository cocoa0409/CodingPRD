"""Pytest bridge between the shared test infrastructure and the test suite.

The service under test is restarted by the harness before every individual
test, so each test starts against an empty database.  Nothing here is
session-scoped except the HTTP client itself.
"""

import pytest

from test_helpers.api_client import api_client
from test_helpers.fixtures import *  # noqa: F401,F403
from test_helpers.test_users import (
    ANALYST_HEADERS,
    COACH_ALT_USER_ID,
    COACH_HEADERS,
    INTRADAY_HEADERS,
    PLANNER_HEADERS,
    SCHEDULER_HEADERS,
    SOURCING_ALT_USER_ID,
    SOURCING_HEADERS,
    make_agent_headers,
    make_coach_headers,
    make_partner_rep_headers,
    make_sourcing_headers,
)


@pytest.fixture(scope="session")
def api():
    """The HTTP client for the service under test."""
    return api_client


# ─── Opaque-role acting principals ────────────────────

@pytest.fixture
def planner(api):
    """Headers for a CapacityPlanner."""
    return PLANNER_HEADERS


@pytest.fixture
def analyst(api):
    """Headers for a WorkforceAnalyst."""
    return ANALYST_HEADERS


@pytest.fixture
def scheduler(api):
    """Headers for a SchedulingManager."""
    return SCHEDULER_HEADERS


@pytest.fixture
def controller(api):
    """Headers for an IntradayController."""
    return INTRADAY_HEADERS


@pytest.fixture
def coach(api):
    """Headers for the primary TeamCoach."""
    return COACH_HEADERS


@pytest.fixture
def other_coach(api):
    """Headers for a second TeamCoach, for maker-checker separation."""
    return make_coach_headers(COACH_ALT_USER_ID)


@pytest.fixture
def sourcer(api):
    """Headers for the proposing SourcingManager."""
    return SOURCING_HEADERS


@pytest.fixture
def other_sourcer(api):
    """Headers for the committing SourcingManager, distinct from the proposer."""
    return make_sourcing_headers(SOURCING_ALT_USER_ID)


# ─── Entity-backed acting principals ──────────────────

@pytest.fixture
def as_agent():
    """Build Agent-role headers carrying the acting agent row's own id."""
    return make_agent_headers


@pytest.fixture
def as_partner_rep():
    """Build PartnerRep-role headers carrying the acting partner row's own id."""
    return make_partner_rep_headers
