"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS, NO_AUTH_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def requester_headers():
    return TEST_USERS["requester_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def appeal_authority_headers():
    return TEST_USERS["appeal_authority_headers"]


@pytest.fixture
def submitter_headers():
    return TEST_USERS["submitter_headers"]


@pytest.fixture
def no_auth_headers():
    return NO_AUTH_HEADERS
