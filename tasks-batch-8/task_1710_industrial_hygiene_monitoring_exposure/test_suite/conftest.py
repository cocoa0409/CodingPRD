"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def firm_admin_headers():
    return TEST_USERS["firm_admin_headers"]


@pytest.fixture
def ih_headers():
    return TEST_USERS["ih_headers"]


@pytest.fixture
def ih2_headers():
    return TEST_USERS["ih2_headers"]


@pytest.fixture
def cih_headers():
    return TEST_USERS["cih_headers"]


@pytest.fixture
def cih2_headers():
    return TEST_USERS["cih2_headers"]


@pytest.fixture
def tech_headers():
    return TEST_USERS["tech_headers"]


@pytest.fixture
def lab_headers():
    return TEST_USERS["lab_headers"]


@pytest.fixture
def lab2_headers():
    return TEST_USERS["lab2_headers"]


@pytest.fixture
def ssm_headers():
    return TEST_USERS["ssm_headers"]


@pytest.fixture
def employee_headers():
    return TEST_USERS["employee_headers"]
