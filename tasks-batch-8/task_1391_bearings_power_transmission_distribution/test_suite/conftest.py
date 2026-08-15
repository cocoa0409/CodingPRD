"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def pricing_analyst_headers():
    return TEST_USERS["pricing_analyst_headers"]


@pytest.fixture
def contract_admin_headers():
    return TEST_USERS["contract_admin_headers"]


@pytest.fixture
def counter_sales_rep_headers():
    return TEST_USERS["counter_sales_rep_headers"]


@pytest.fixture
def branch_manager_headers():
    return TEST_USERS["branch_manager_headers"]


@pytest.fixture
def on_call_technician_headers():
    return TEST_USERS["on_call_technician_headers"]


@pytest.fixture
def warranty_analyst_headers():
    return TEST_USERS["warranty_analyst_headers"]


@pytest.fixture
def quality_engineer_headers():
    return TEST_USERS["quality_engineer_headers"]
