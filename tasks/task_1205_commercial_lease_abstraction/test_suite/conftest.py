"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def portfolio_manager_headers():
    return TEST_USERS["portfolio_manager_headers"]


@pytest.fixture
def property_manager_headers():
    return TEST_USERS["property_manager_headers"]


@pytest.fixture
def lease_accountant_headers():
    return TEST_USERS["lease_accountant_headers"]


@pytest.fixture
def abstractor_headers():
    return TEST_USERS["abstractor_headers"]


@pytest.fixture
def certifier_headers():
    return TEST_USERS["certifier_headers"]
