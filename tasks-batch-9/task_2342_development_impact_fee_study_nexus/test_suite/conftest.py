"""Pytest fixtures exposing the shared test infrastructure.

The service is relaunched against an empty database before every test, so each
test builds all of its own state through the endpoints the contract declares.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The HTTP client for the service under test."""
    return api_client


@pytest.fixture(scope="session")
def users():
    """Header sets for the acting identities used across the suite."""
    return TEST_USERS
