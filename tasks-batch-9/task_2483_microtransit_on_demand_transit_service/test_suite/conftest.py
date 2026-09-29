"""Shared pytest fixtures for the microtransit on-demand transit test suite.

The server is already running when these tests execute and its database is empty
at the start of every individual test, so each fixture composes the state it
needs from scratch through the public endpoints.
"""

import pytest

from test_helpers.api_client import api_client
from test_helpers.fixtures import (  # noqa: F401  (re-exported as fixtures)
    accepted_trip,
    active_zone,
    capped_zone_ready,
    certified_report,
    clock,
    closed_block,
    completed_trip,
    dispatch_ready,
    draft_report,
    draft_zone,
    offered_trip,
    onboard_trip,
    received_trip,
    roomy_curb_ready,
    scheduling_sandbox,
    submitted_report,
    two_open_blocks,
    zone_with_corridor,
)
from test_helpers.test_users import (
    AUDITOR_2_HEADERS,
    AUDITOR_HEADERS,
    DISPATCHER_HEADERS,
    FINANCE_ANALYST_2_HEADERS,
    FINANCE_ANALYST_HEADERS,
    ZONE_ADMIN_HEADERS,
)


@pytest.fixture
def client():
    """The API client bound to the running server."""
    return api_client


@pytest.fixture
def zone_admin_headers():
    return ZONE_ADMIN_HEADERS


@pytest.fixture
def dispatcher_headers():
    return DISPATCHER_HEADERS


@pytest.fixture
def finance_analyst_headers():
    return FINANCE_ANALYST_HEADERS


@pytest.fixture
def finance_analyst_2_headers():
    return FINANCE_ANALYST_2_HEADERS


@pytest.fixture
def auditor_headers():
    return AUDITOR_HEADERS


@pytest.fixture
def auditor_2_headers():
    return AUDITOR_2_HEADERS
