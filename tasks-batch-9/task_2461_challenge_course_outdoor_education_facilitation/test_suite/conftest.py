"""Shared pytest fixtures for the Challenge Course Operations API suite.

The server is already running when these tests execute and each test starts
against an empty database, so every fixture below is function-scoped and builds
whatever state its test needs through the public API.
"""

import pytest

from test_helpers import ApiClient
from test_helpers.constants import CLOCK_TEST_DATE, CLOCK_TEST_UTC
from test_helpers.fixtures import set_clock


@pytest.fixture
def api():
    """HTTP client bound to the API under test."""
    return ApiClient()


@pytest.fixture
def clock(api):
    """Pin the logical clock to a fixed instant and return its date part."""
    set_clock(api, CLOCK_TEST_UTC)
    return CLOCK_TEST_DATE


@pytest.fixture
def clock_instant():
    """The instant the `clock` fixture pins."""
    return CLOCK_TEST_UTC
