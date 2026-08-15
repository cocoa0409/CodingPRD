"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def steward_headers():
    return TEST_USERS["steward_headers"]


@pytest.fixture
def lead_headers():
    return TEST_USERS["lead_headers"]


@pytest.fixture
def assurer_headers():
    return TEST_USERS["assurer_headers"]


@pytest.fixture
def supplier_headers():
    return TEST_USERS["supplier_headers"]
