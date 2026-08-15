"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def import_coordinator_headers():
    return TEST_USERS["import_coordinator_headers"]


@pytest.fixture
def receiving_inspector_headers():
    return TEST_USERS["receiving_inspector_headers"]


@pytest.fixture
def qa_tech_headers():
    return TEST_USERS["qa_tech_headers"]


@pytest.fixture
def processing_supervisor_headers():
    return TEST_USERS["processing_supervisor_headers"]


@pytest.fixture
def compliance_manager_headers():
    return TEST_USERS["compliance_manager_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
