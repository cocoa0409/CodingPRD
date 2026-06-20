"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def pm_headers():
    return TEST_USERS["property_manager_headers"]


@pytest.fixture
def meter_tech_headers():
    return TEST_USERS["meter_tech_headers"]


@pytest.fixture
def tenant_headers():
    return TEST_USERS["tenant_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
