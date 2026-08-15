"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def casting_director_headers():
    return TEST_USERS["casting_director_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]


@pytest.fixture
def talent_headers():
    return TEST_USERS["talent_headers"]


@pytest.fixture
def studio_engineer_headers():
    return TEST_USERS["studio_engineer_headers"]


@pytest.fixture
def agent_headers():
    return TEST_USERS["agent_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
