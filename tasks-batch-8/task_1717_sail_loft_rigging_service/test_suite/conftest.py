"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def loft_manager_headers():
    return TEST_USERS["loft_manager_headers"]


@pytest.fixture
def sailmaker_headers():
    return TEST_USERS["sailmaker_headers"]


@pytest.fixture
def measurer_headers():
    return TEST_USERS["measurer_headers"]


@pytest.fixture
def rigger_headers():
    return TEST_USERS["rigger_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
