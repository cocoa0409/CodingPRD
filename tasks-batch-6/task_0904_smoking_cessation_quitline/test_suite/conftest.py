"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS, NO_AUTH_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def case_manager_headers():
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def participant_headers():
    return TEST_USERS["participant_headers"]


@pytest.fixture
def no_auth_headers():
    return NO_AUTH_HEADERS
