"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS, UNKNOWN_ROLE_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def revenue_manager_headers():
    return TEST_USERS["revenue_manager_headers"]


@pytest.fixture
def group_sales_manager_headers():
    return TEST_USERS["group_sales_manager_headers"]


@pytest.fixture
def channel_manager_headers():
    return TEST_USERS["channel_manager_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def unknown_role_headers():
    return UNKNOWN_ROLE_HEADERS
