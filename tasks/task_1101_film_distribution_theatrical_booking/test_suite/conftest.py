"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def booker_headers():
    return TEST_USERS["booker_headers"]


@pytest.fixture
def exhibitor_headers():
    return TEST_USERS["exhibitor_headers"]


@pytest.fixture
def settlement_clerk_headers():
    return TEST_USERS["settlement_clerk_headers"]


@pytest.fixture
def marketing_lead_headers():
    return TEST_USERS["marketing_lead_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
