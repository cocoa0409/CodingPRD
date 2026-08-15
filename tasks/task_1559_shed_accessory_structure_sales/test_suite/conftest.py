"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def sales_rep_headers():
    return TEST_USERS["sales_rep_headers"]


@pytest.fixture
def permit_coordinator_headers():
    return TEST_USERS["permit_coordinator_headers"]


@pytest.fixture
def install_crew_headers():
    return TEST_USERS["install_crew_headers"]


@pytest.fixture
def finance_manager_headers():
    return TEST_USERS["finance_manager_headers"]


@pytest.fixture
def operations_admin_headers():
    return TEST_USERS["operations_admin_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
