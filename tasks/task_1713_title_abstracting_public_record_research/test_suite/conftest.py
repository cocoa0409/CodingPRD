"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]


@pytest.fixture
def abstracter_headers():
    return TEST_USERS["abstracter_headers"]


@pytest.fixture
def examiner_headers():
    return TEST_USERS["examiner_headers"]


@pytest.fixture
def ops_manager_headers():
    return TEST_USERS["ops_manager_headers"]
