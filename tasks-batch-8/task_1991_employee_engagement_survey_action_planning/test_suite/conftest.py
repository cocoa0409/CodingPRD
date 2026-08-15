"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def hr_admin_headers():
    return TEST_USERS["hr_admin_headers"]


@pytest.fixture
def people_analyst_headers():
    return TEST_USERS["people_analyst_headers"]


@pytest.fixture
def executive_headers():
    return TEST_USERS["executive_headers"]


@pytest.fixture
def unit_manager_headers():
    return TEST_USERS["unit_manager_headers"]


@pytest.fixture
def employee_role_headers():
    return TEST_USERS["employee_role_headers"]
