"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def sales_engineer_headers():
    return TEST_USERS["sales_engineer_headers"]


@pytest.fixture
def design_engineer_headers():
    return TEST_USERS["design_engineer_headers"]


@pytest.fixture
def quality_engineer_headers():
    return TEST_USERS["quality_engineer_headers"]


@pytest.fixture
def plant_manager_headers():
    return TEST_USERS["plant_manager_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
