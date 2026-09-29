"""Shared fixtures for the compliance suite.

The harness restarts the server and resets its database before every test, so
each test starts from an empty catalog with the logical clock at its untouched
default.  Fixtures here therefore hand out a client and a scenario builder rather
than pre-seeded data.
"""

import pytest

from test_helpers import ApiClient, Scenario
from test_helpers.fixtures import CLOCK_9AM


@pytest.fixture
def api():
    """HTTP client for the API under test."""
    return ApiClient()


@pytest.fixture
def scenario(api):
    """Builder for the multi-step setups the workflows require."""
    return Scenario(api)


@pytest.fixture
def clock_at_nine(scenario):
    """Pin the logical clock at 2026-08-10T09:00:00Z, a plain mid-morning instant."""
    scenario.set_clock(CLOCK_9AM)
    return CLOCK_9AM
