"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def finance_admin_headers():
    return TEST_USERS["finance_admin_headers"]


@pytest.fixture
def project_engineer_headers():
    """Shared ProjectEngineer headers — only for calls that are not
    ownership-gated. For ownership-gated calls use
    make_project_engineer_headers(user_id)."""
    return TEST_USERS["project_engineer_headers"]


@pytest.fixture
def safety_lead_headers():
    return TEST_USERS["safety_lead_headers"]


@pytest.fixture
def controls_programmer_headers():
    return TEST_USERS["controls_programmer_headers"]


@pytest.fixture
def site_supervisor_headers():
    return TEST_USERS["site_supervisor_headers"]


@pytest.fixture
def trainer_headers():
    return TEST_USERS["trainer_headers"]


@pytest.fixture
def service_manager_headers():
    return TEST_USERS["service_manager_headers"]
