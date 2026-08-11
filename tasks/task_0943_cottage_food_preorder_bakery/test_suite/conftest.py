"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["health_inspector_headers"]


@pytest.fixture
def baker_headers():
    """Shared Baker headers — only for tests that do not exercise ownership."""
    return TEST_USERS["baker_headers"]


@pytest.fixture
def customer_headers():
    """Shared Customer headers — only for tests that do not exercise ownership."""
    return TEST_USERS["customer_headers"]
