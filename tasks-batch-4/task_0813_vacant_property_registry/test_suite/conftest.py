"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner,
    which restarts the server (and resets the logical clock) before each test."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def registrant_headers():
    return TEST_USERS["registrant_headers"]


@pytest.fixture
def code_officer_headers():
    return TEST_USERS["code_officer_headers"]


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]
