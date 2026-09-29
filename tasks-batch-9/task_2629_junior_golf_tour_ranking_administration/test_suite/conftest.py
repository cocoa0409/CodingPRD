"""Shared pytest fixtures for the junior golf tour compliance suite.

The server is started by the harness before each test and torn down afterwards, so
every test begins against an empty database and builds the state it needs through
the documented endpoints.
"""

import os

import pytest

from test_helpers.api_client import GolfTourApiClient


@pytest.fixture
def api():
    """A client pointed at the server under test."""
    return GolfTourApiClient(os.environ.get("API_BASE_URL"))
