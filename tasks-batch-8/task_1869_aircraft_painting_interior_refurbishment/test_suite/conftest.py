"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def center_admin_headers():
    return TEST_USERS["center_admin_headers"]


@pytest.fixture
def program_manager_headers():
    return TEST_USERS["program_manager_headers"]


@pytest.fixture
def design_lead_headers():
    return TEST_USERS["design_lead_headers"]


@pytest.fixture
def shop_technician_headers():
    return TEST_USERS["shop_technician_headers"]


@pytest.fixture
def quality_inspector_headers():
    return TEST_USERS["quality_inspector_headers"]


@pytest.fixture
def finance_clerk_headers():
    return TEST_USERS["finance_clerk_headers"]


@pytest.fixture
def customer_rep_headers():
    return TEST_USERS["customer_rep_headers"]
