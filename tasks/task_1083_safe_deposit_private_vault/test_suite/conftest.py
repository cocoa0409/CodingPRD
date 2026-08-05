"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def vault_admin_headers():
    return TEST_USERS["vault_admin_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def vault_officer_headers():
    return TEST_USERS["vault_officer_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def renter_headers():
    return TEST_USERS["renter_headers"]
