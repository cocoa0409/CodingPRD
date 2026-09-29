"""Pytest fixtures exposing the allocation test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def planning_admin_headers():
    return TEST_USERS["planning_admin_headers"]


@pytest.fixture
def allocator_headers():
    return TEST_USERS["allocator_headers"]


@pytest.fixture
def allocation_manager_headers():
    return TEST_USERS["allocation_manager_headers"]


@pytest.fixture
def second_allocator_headers():
    return TEST_USERS["second_allocator_headers"]


@pytest.fixture
def second_manager_headers():
    return TEST_USERS["second_manager_headers"]


@pytest.fixture
def store_operator_headers():
    """Fallback StoreOperator headers whose X-User-ID is not any real Store id.
    Use only where the test does not depend on the caller owning the store."""
    return TEST_USERS["store_operator_headers"]
