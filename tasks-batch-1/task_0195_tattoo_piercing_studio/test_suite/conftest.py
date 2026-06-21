"""Pytest fixtures exposing test_helpers infrastructure. Server lifecycle is
managed by prd-bench-local-runner; these tests assume the server is already
running and reachable at API_BASE_URL.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def artist_headers():
    return TEST_USERS["artist_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
