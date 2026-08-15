"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def sales_rep_headers():
    return TEST_USERS["sales_rep_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def manufacturer_agent_headers():
    return TEST_USERS["manufacturer_agent_headers"]


@pytest.fixture
def practice_manager_headers():
    return TEST_USERS["practice_manager_headers"]


@pytest.fixture
def field_technician_headers():
    return TEST_USERS["field_technician_headers"]
