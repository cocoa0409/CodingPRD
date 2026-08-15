"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def shop_manager_headers():
    return TEST_USERS["shop_manager_headers"]


@pytest.fixture
def technician_headers():
    return TEST_USERS["technician_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def customer_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["customer_headers"]
