"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def producer_headers():
    return TEST_USERS["producer_headers"]


@pytest.fixture
def tour_manager_headers():
    return TEST_USERS["tour_manager_headers"]


@pytest.fixture
def company_manager_headers():
    return TEST_USERS["company_manager_headers"]


@pytest.fixture
def treasurer_headers():
    return TEST_USERS["treasurer_headers"]
