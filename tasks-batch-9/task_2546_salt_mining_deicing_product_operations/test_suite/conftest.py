"""
Shared pytest fixtures for the Salt Deicing Operations API compliance suite.

The server is already running and owned by the harness; the database is empty at
the start of every test, so every test builds the state it asserts on through
published endpoints. The logical clock likewise starts on the documented instant of
PRD §2.5 for every test, so a test only moves it when the scenario needs a
different "now".
"""

import pytest

from test_helpers import SaltApiClient


@pytest.fixture
def api() -> SaltApiClient:
    """Client bound to the API under test (base URL from API_BASE_URL)."""
    return SaltApiClient()
