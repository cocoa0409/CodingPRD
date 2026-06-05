"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; tests assume the server is
already running and reachable at API_BASE_URL, against an empty database that is
reset before every individual test.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def authority_headers():
    return TEST_USERS["authority_headers"]


@pytest.fixture
def resident_headers():
    return TEST_USERS["resident_headers"]
