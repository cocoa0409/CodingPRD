"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS, ANONYMOUS_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["election_admin_headers"]


@pytest.fixture
def captain_headers():
    return TEST_USERS["precinct_captain_headers"]


@pytest.fixture
def poll_worker_headers():
    return TEST_USERS["poll_worker_headers"]


@pytest.fixture
def custody_headers():
    return TEST_USERS["custody_officer_headers"]


@pytest.fixture
def support_headers():
    return TEST_USERS["support_agent_headers"]


@pytest.fixture
def anonymous_headers():
    return ANONYMOUS_HEADERS
