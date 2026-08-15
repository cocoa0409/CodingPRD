"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def enrollment_officer_headers():
    return TEST_USERS["enrollment_officer_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def academic_director_headers():
    return TEST_USERS["academic_director_headers"]


@pytest.fixture
def proctor_coordinator_headers():
    return TEST_USERS["proctor_coordinator_headers"]


@pytest.fixture
def special_ed_coordinator_headers():
    return TEST_USERS["special_ed_coordinator_headers"]
