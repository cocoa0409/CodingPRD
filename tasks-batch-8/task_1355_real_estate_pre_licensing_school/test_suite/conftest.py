"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def state_commission_headers():
    return TEST_USERS["state_commission_headers"]


@pytest.fixture
def school_director_headers():
    return TEST_USERS["school_director_headers"]


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def instructor_headers():
    return TEST_USERS["instructor_headers"]


@pytest.fixture
def proctor_headers():
    return TEST_USERS["proctor_headers"]


@pytest.fixture
def student_headers():
    return TEST_USERS["student_headers"]
