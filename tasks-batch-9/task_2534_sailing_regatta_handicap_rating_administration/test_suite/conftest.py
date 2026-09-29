"""Shared fixtures for the PRD compliance suite.

The harness relaunches the API server against an empty database before every
individual test, so nothing here tears anything down: each test builds the exact
world it asserts on, from scratch, through PRD-declared endpoints only.
"""

import pytest

from test_helpers import api_client, enrol_standard_roster, roster_headers


@pytest.fixture
def api():
    """The endpoint-per-method client rooted at the `/regatta-ops` prefix."""
    return api_client


@pytest.fixture
def roster():
    """A ten-strong club roster: measurer, chair, three committee volunteers,
    two judges and three helms carrying a valid sea-survival course."""
    return enrol_standard_roster()


@pytest.fixture
def headers(roster):
    """Role headers bound to the roster members, one per acting capacity."""
    return roster_headers(roster)
