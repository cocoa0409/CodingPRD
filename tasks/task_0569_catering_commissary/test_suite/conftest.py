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
def kitchen_manager_headers():
    return TEST_USERS["kitchen_manager_headers"]


@pytest.fixture
def sales_manager_headers():
    return TEST_USERS["sales_manager_headers"]


@pytest.fixture
def event_captain_headers():
    return TEST_USERS["event_captain_headers"]


@pytest.fixture
def no_auth_headers():
    return NO_AUTH_HEADERS
