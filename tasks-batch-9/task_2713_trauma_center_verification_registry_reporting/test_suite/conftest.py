"""Shared pytest configuration for the Trauma Verification Registry suite.

Server start-up, liveness and per-test database isolation are owned by the runner, so
nothing here manages a process. What each test does need is a client bound to the
service under test and a logical clock pinned to a known instant, and both are supplied
below.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """A client for the service under test, fresh for every test."""
    return ApiClient()


@pytest.fixture
def clock(api: ApiClient) -> str:
    """The logical clock pinned to its start-up instant.

    A test that needs a different instant moves the clock itself; requesting this
    fixture only guarantees the starting point rather than trusting start-up state.
    """
    return fx.anchor_clock(api)["current_utc"]
