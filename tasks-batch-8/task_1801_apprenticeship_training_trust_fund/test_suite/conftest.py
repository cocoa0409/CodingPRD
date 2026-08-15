"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def trust_admin_headers():
    return TEST_USERS["trust_admin_headers"]


@pytest.fixture
def trust_admin2_headers():
    return TEST_USERS["trust_admin2_headers"]


@pytest.fixture
def committee_member_headers():
    return TEST_USERS["committee_member_headers"]


@pytest.fixture
def committee_member2_headers():
    return TEST_USERS["committee_member2_headers"]


@pytest.fixture
def employer_rep_headers():
    return TEST_USERS["employer_rep_headers"]


@pytest.fixture
def instructor_headers():
    return TEST_USERS["instructor_headers"]
