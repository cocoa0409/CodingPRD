"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def plan_admin_headers():
    return TEST_USERS["plan_admin_headers"]


@pytest.fixture
def contract_manager_headers():
    return TEST_USERS["contract_manager_headers"]


@pytest.fixture
def contract_legal_headers():
    return TEST_USERS["contract_legal_headers"]


@pytest.fixture
def configuration_analyst_headers():
    return TEST_USERS["configuration_analyst_headers"]


@pytest.fixture
def payment_integrity_headers():
    return TEST_USERS["payment_integrity_headers"]


@pytest.fixture
def provider_rep_headers():
    return TEST_USERS["provider_rep_headers"]
