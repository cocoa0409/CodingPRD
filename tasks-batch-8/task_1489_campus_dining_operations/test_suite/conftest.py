"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def dining_admin_headers():
    return TEST_USERS["dining_admin_headers"]


@pytest.fixture
def hall_manager_headers():
    return TEST_USERS["hall_manager_headers"]


@pytest.fixture
def kitchen_lead_headers():
    return TEST_USERS["kitchen_lead_headers"]


@pytest.fixture
def dietitian_headers():
    return TEST_USERS["dietitian_headers"]


@pytest.fixture
def health_inspector_headers():
    return TEST_USERS["health_inspector_headers"]


@pytest.fixture
def contract_manager_headers():
    return TEST_USERS["contract_manager_headers"]


@pytest.fixture
def department_user_headers():
    return TEST_USERS["department_user_headers"]
