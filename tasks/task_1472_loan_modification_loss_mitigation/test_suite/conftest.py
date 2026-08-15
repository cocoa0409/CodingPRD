"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def borrower_headers():
    return TEST_USERS["borrower_headers"]


@pytest.fixture
def agent_headers():
    return TEST_USERS["agent_headers"]


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def ops_headers():
    return TEST_USERS["ops_headers"]


@pytest.fixture
def counsel_headers():
    return TEST_USERS["counsel_headers"]
