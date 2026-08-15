"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def broker_admin_headers():
    return TEST_USERS["broker_admin_headers"]


@pytest.fixture
def office_manager_headers():
    return TEST_USERS["office_manager_headers"]


@pytest.fixture
def transaction_coordinator_headers():
    return TEST_USERS["transaction_coordinator_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def agent_headers():
    return TEST_USERS["agent_headers"]
