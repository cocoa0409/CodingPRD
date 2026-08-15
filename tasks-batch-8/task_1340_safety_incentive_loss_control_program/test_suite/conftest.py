"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def ehs_admin_headers():
    return TEST_USERS["ehs_admin_headers"]


@pytest.fixture
def safety_manager_headers():
    return TEST_USERS["safety_manager_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def employee_headers():
    return TEST_USERS["employee_headers"]


@pytest.fixture
def committee_chair_headers():
    return TEST_USERS["committee_chair_headers"]


@pytest.fixture
def contractor_rep_headers():
    return TEST_USERS["contractor_rep_headers"]


@pytest.fixture
def carrier_consultant_headers():
    return TEST_USERS["carrier_consultant_headers"]
