"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def receiving_clerk_headers():
    return TEST_USERS["receiving_clerk_headers"]


@pytest.fixture
def storage_operator_headers():
    return TEST_USERS["storage_operator_headers"]


@pytest.fixture
def packing_supervisor_headers():
    return TEST_USERS["packing_supervisor_headers"]


@pytest.fixture
def pool_manager_headers():
    return TEST_USERS["pool_manager_headers"]


@pytest.fixture
def grower_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["grower_headers"]
