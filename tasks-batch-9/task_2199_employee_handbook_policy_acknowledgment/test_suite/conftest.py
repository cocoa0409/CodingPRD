"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def author_headers():
    return TEST_USERS["author_headers"]


@pytest.fixture
def localizer_headers():
    return TEST_USERS["localizer_headers"]


@pytest.fixture
def counsel_headers():
    return TEST_USERS["counsel_headers"]


@pytest.fixture
def employee_headers():
    return TEST_USERS["employee_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]
