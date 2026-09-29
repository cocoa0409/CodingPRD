"""Pytest fixtures exposing the shared test infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def rtw_coordinator_headers():
    return TEST_USERS["rtw_coordinator_headers"]


@pytest.fixture
def occ_health_nurse_headers():
    return TEST_USERS["occ_health_nurse_headers"]


@pytest.fixture
def second_nurse_headers():
    return TEST_USERS["second_nurse_headers"]


@pytest.fixture
def claim_adjuster_headers():
    return TEST_USERS["claim_adjuster_headers"]


@pytest.fixture
def treating_provider_headers():
    return TEST_USERS["treating_provider_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def employee_headers():
    return TEST_USERS["employee_headers"]
