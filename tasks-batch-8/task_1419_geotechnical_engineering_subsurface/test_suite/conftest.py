"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def firm_admin_headers():
    return TEST_USERS["firm_admin_headers"]


@pytest.fixture
def client_rep_headers():
    return TEST_USERS["client_rep_headers"]


@pytest.fixture
def project_manager_headers():
    return TEST_USERS["project_manager_headers"]


@pytest.fixture
def staff_engineer_headers():
    return TEST_USERS["staff_engineer_headers"]


@pytest.fixture
def field_geologist_headers():
    return TEST_USERS["field_geologist_headers"]


@pytest.fixture
def drilling_sub_headers():
    return TEST_USERS["drilling_sub_headers"]


@pytest.fixture
def lab_manager_headers():
    return TEST_USERS["lab_manager_headers"]


@pytest.fixture
def lab_technician_headers():
    return TEST_USERS["lab_technician_headers"]


@pytest.fixture
def senior_engineer_headers():
    return TEST_USERS["senior_engineer_headers"]


@pytest.fixture
def principal_engineer_headers():
    return TEST_USERS["principal_engineer_headers"]
