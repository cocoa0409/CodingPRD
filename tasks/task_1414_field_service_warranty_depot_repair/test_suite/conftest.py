"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def intake_agent_headers():
    return TEST_USERS["intake_agent_headers"]


@pytest.fixture
def depot_technician_headers():
    return TEST_USERS["depot_technician_headers"]


@pytest.fixture
def depot_manager_headers():
    return TEST_USERS["depot_manager_headers"]


@pytest.fixture
def warranty_admin_headers():
    return TEST_USERS["warranty_admin_headers"]


@pytest.fixture
def engineering_lead_headers():
    return TEST_USERS["engineering_lead_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
