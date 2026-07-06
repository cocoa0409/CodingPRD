"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS, NO_AUTH_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def facility_admin_headers():
    return TEST_USERS["facility_admin_headers"]


@pytest.fixture
def box_office_headers():
    return TEST_USERS["box_office_headers"]


@pytest.fixture
def group_sales_headers():
    return TEST_USERS["group_sales_headers"]


@pytest.fixture
def membership_clerk_headers():
    return TEST_USERS["membership_clerk_headers"]


@pytest.fixture
def program_coordinator_headers():
    return TEST_USERS["program_coordinator_headers"]


@pytest.fixture
def events_manager_headers():
    return TEST_USERS["events_manager_headers"]


@pytest.fixture
def development_officer_headers():
    return TEST_USERS["development_officer_headers"]


@pytest.fixture
def accessibility_headers():
    return TEST_USERS["accessibility_headers"]


@pytest.fixture
def no_auth_headers():
    return NO_AUTH_HEADERS
