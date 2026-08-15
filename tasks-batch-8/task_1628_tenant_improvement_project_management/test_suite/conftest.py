"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def landlord_pm_headers():
    return TEST_USERS["landlord_pm_headers"]


@pytest.fixture
def landlord_approver_headers():
    return TEST_USERS["landlord_approver_headers"]


@pytest.fixture
def tenant_rep_headers():
    return TEST_USERS["tenant_rep_headers"]


@pytest.fixture
def contractor_rep_headers():
    return TEST_USERS["contractor_rep_headers"]


@pytest.fixture
def building_engineer_headers():
    return TEST_USERS["building_engineer_headers"]
