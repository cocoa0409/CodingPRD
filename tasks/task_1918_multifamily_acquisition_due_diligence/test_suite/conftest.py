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
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def underwriting_manager_headers():
    return TEST_USERS["underwriting_manager_headers"]


@pytest.fixture
def property_ops_headers():
    return TEST_USERS["property_ops_headers"]


@pytest.fixture
def hr_partner_headers():
    return TEST_USERS["hr_partner_headers"]


@pytest.fixture
def vendor_manager_headers():
    return TEST_USERS["vendor_manager_headers"]


@pytest.fixture
def escrow_officer_headers():
    return TEST_USERS["escrow_officer_headers"]
