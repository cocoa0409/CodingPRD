"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The API client bound to the service under test."""
    return api_client


@pytest.fixture(scope="session")
def users() -> dict:
    """Pre-built identity headers for the roles with opaque user ids."""
    return TEST_USERS
