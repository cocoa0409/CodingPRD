"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def talent_manager_headers():
    return TEST_USERS["talent_manager_headers"]


@pytest.fixture
def brand_manager_headers():
    return TEST_USERS["brand_manager_headers"]


@pytest.fixture
def brand_manager_2_headers():
    return TEST_USERS["brand_manager_2_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def finance_admin_headers():
    return TEST_USERS["finance_admin_headers"]


@pytest.fixture
def finance_admin_2_headers():
    return TEST_USERS["finance_admin_2_headers"]
