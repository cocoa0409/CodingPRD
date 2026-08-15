"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def intake_specialist_headers():
    return TEST_USERS["intake_specialist_headers"]


@pytest.fixture
def supervising_attorney_headers():
    return TEST_USERS["supervising_attorney_headers"]


@pytest.fixture
def staff_attorney_headers():
    return TEST_USERS["staff_attorney_headers"]


@pytest.fixture
def paralegal_headers():
    return TEST_USERS["paralegal_headers"]


@pytest.fixture
def ethics_officer_headers():
    return TEST_USERS["ethics_officer_headers"]


@pytest.fixture
def grants_manager_headers():
    return TEST_USERS["grants_manager_headers"]


@pytest.fixture
def program_director_headers():
    return TEST_USERS["program_director_headers"]
