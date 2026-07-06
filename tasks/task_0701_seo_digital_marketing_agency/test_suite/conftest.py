"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle, PYTHONPATH, and API_BASE_URL are managed by prd-bench-local-runner.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The runner restarts the server before each test."""
    return api_client


@pytest.fixture
def agency_admin_headers():
    return TEST_USERS["agency_admin_headers"]


@pytest.fixture
def account_manager_headers():
    return TEST_USERS["account_manager_headers"]


@pytest.fixture
def reseller_headers():
    return TEST_USERS["reseller_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]
