"""
Shared pytest fixtures for the Prepaid Restaurant Ticketing API test suite.

The runner owns the server lifecycle and publishes ``API_BASE_URL``; the suite
assumes a server that is already listening and a database that is empty at the
start of every test. Nothing here creates domain state — each test builds its
own preconditions through declared endpoints only.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402
from test_helpers import fixtures as FX  # noqa: E402


@pytest.fixture()
def api() -> ApiClient:
    """A client pointed at the server under test."""
    return ApiClient()


@pytest.fixture()
def clock(api: ApiClient):
    """The logical clock, pinned to the recurring setup instant.

    The logical clock reads exactly 2026-08-01T00:00:00Z before any request
    sets it; every scenario below moves it forward explicitly so that no hold,
    offer, cutoff or release window is already lapsed.
    """
    FX.set_clock(api, FX.SETUP_CLOCK)
    return FX.SETUP_CLOCK
