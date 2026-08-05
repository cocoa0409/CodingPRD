"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS, ANON_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def authority_headers():
    return TEST_USERS["authority_headers"]


@pytest.fixture
def confirming_headers():
    return TEST_USERS["confirming_headers"]


@pytest.fixture
def ethics_headers():
    return TEST_USERS["ethics_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def anon_headers():
    return ANON_HEADERS
