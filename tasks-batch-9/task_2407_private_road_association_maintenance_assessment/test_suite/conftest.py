"""Pytest fixtures exposing the shared test infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def secretary_headers():
    return TEST_USERS["secretary_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def treasurer_headers():
    return TEST_USERS["treasurer_headers"]


@pytest.fixture
def treasurer_two_headers():
    return TEST_USERS["treasurer_two_headers"]


@pytest.fixture
def commissioner_headers():
    return TEST_USERS["commissioner_headers"]


@pytest.fixture
def commissioner_two_headers():
    return TEST_USERS["commissioner_two_headers"]


@pytest.fixture
def contractor_headers():
    return TEST_USERS["contractor_headers"]


@pytest.fixture
def contractor_two_headers():
    return TEST_USERS["contractor_two_headers"]


@pytest.fixture
def contractor_three_headers():
    return TEST_USERS["contractor_three_headers"]


@pytest.fixture
def member_owner_headers():
    return TEST_USERS["member_owner_headers"]
