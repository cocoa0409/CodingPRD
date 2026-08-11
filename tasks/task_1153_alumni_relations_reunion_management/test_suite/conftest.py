"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns server lifecycle and injects API_BASE_URL; the suite assumes
the server is already running and reachable.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def staff_headers():
    return TEST_USERS["staff_headers"]


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]
