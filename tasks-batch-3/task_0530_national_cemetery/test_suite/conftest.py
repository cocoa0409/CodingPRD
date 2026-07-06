"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS, NO_AUTH_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def eligibility_officer_headers():
    return TEST_USERS["eligibility_officer_headers"]


@pytest.fixture
def scheduling_clerk_headers():
    return TEST_USERS["scheduling_clerk_headers"]


@pytest.fixture
def marker_clerk_headers():
    return TEST_USERS["marker_clerk_headers"]


@pytest.fixture
def honors_coordinator_headers():
    return TEST_USERS["honors_coordinator_headers"]


@pytest.fixture
def no_auth_headers():
    return NO_AUTH_HEADERS
