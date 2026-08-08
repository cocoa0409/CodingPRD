"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS, ANON_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def agent_headers():
    return TEST_USERS["collections_agent_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def trustee_headers():
    return TEST_USERS["trust_accountant_headers"]


@pytest.fixture
def anon_headers():
    return ANON_HEADERS
