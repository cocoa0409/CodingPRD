"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS, ANONYMOUS_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_headers():
    return TEST_USERS["platform_headers"]


@pytest.fixture
def anonymous_headers():
    return ANONYMOUS_HEADERS
