"""Shared pytest configuration for the beverage-program compliance suite.

The runner relaunches the API server before every individual test, so each test
starts against an empty database and must build all of its preconditions through
the published endpoints.  Nothing here may cache domain data across tests.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_errors  # noqa: E402,F401  (registers the status map)
from test_helpers.api_client import ApiClient, api_client  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """The client pointed at the API under test."""
    return api_client
