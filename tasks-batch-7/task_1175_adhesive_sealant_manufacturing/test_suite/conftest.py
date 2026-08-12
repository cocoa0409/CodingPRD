"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def plant_manager_headers():
    return TEST_USERS["plant_manager_headers"]


@pytest.fixture
def batch_operator_headers():
    return TEST_USERS["batch_operator_headers"]


@pytest.fixture
def qa_technician_headers():
    return TEST_USERS["qa_technician_headers"]


@pytest.fixture
def qa_manager_headers():
    return TEST_USERS["qa_manager_headers"]


@pytest.fixture
def tech_service_headers():
    return TEST_USERS["tech_service_headers"]


@pytest.fixture
def commercial_manager_headers():
    return TEST_USERS["commercial_manager_headers"]


@pytest.fixture
def logistics_headers():
    return TEST_USERS["logistics_headers"]


@pytest.fixture
def distributor_headers():
    return TEST_USERS["distributor_headers"]
