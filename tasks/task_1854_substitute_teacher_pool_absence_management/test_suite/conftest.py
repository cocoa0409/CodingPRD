"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import NO_AUTH_HEADERS, TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def district_admin_headers():
    return TEST_USERS["district_admin_headers"]


@pytest.fixture
def payroll_clerk_headers():
    return TEST_USERS["payroll_clerk_headers"]


@pytest.fixture
def school_coordinator_headers():
    return TEST_USERS["school_coordinator_headers"]


@pytest.fixture
def teacher_headers():
    return TEST_USERS["teacher_headers"]


@pytest.fixture
def substitute_headers():
    return TEST_USERS["substitute_headers"]


@pytest.fixture
def no_auth_headers():
    return dict(NO_AUTH_HEADERS)
