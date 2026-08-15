"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def listing_agent_headers():
    return TEST_USERS["listing_agent_headers"]


@pytest.fixture
def marketing_coordinator_headers():
    return TEST_USERS["marketing_coordinator_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def marketing_director_headers():
    return TEST_USERS["marketing_director_headers"]


@pytest.fixture
def portal_webhook_headers():
    return TEST_USERS["portal_webhook_headers"]
