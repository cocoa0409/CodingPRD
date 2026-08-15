"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def firm_admin_headers():
    return TEST_USERS["firm_admin_headers"]


@pytest.fixture
def assessor_clerk_headers():
    return TEST_USERS["assessor_clerk_headers"]


@pytest.fixture
def tax_analyst_headers():
    return TEST_USERS["tax_analyst_headers"]


@pytest.fixture
def senior_manager_headers():
    return TEST_USERS["senior_manager_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]
