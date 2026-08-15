"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def ops_admin_headers():
    return TEST_USERS["ops_admin_headers"]


@pytest.fixture
def compliance_manager_headers():
    return TEST_USERS["compliance_manager_headers"]


@pytest.fixture
def trader_headers():
    return TEST_USERS["trader_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
