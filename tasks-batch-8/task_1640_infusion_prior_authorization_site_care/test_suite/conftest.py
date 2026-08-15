"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def policy_admin_headers():
    return TEST_USERS["policy_admin_headers"]


@pytest.fixture
def auth_coordinator_headers():
    return TEST_USERS["auth_coordinator_headers"]


@pytest.fixture
def medical_director_headers():
    return TEST_USERS["medical_director_headers"]


@pytest.fixture
def medical_director_2_headers():
    return TEST_USERS["medical_director_2_headers"]


@pytest.fixture
def finance_specialist_headers():
    return TEST_USERS["finance_specialist_headers"]


@pytest.fixture
def finance_specialist_2_headers():
    return TEST_USERS["finance_specialist_2_headers"]


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["scheduler_headers"]
