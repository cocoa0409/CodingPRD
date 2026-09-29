"""Shared pytest fixtures for the commission API suite.

The harness starts the API server and injects `API_BASE_URL` before each test,
so every test begins against an empty database at the clock's startup default.
"""

import pytest

from test_helpers import CommissionApiClient
from test_helpers.api_errors import register_error_status_map


@pytest.fixture(scope="session", autouse=True)
def error_status_map():
    """Teach the validators which HTTP status each catalogued error carries."""
    register_error_status_map()


@pytest.fixture
def client() -> CommissionApiClient:
    """A client pointed at the server the harness has already started."""
    return CommissionApiClient()
