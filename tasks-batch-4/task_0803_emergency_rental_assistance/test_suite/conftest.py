"""Pytest fixtures exposing test_helpers infrastructure.

The prd-bench-local-runner sets PYTHONPATH so test_helpers is importable, injects
API_BASE_URL, and restarts the server (empty DB) before every individual test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def caseworker_headers():
    return TEST_USERS["caseworker_headers"]


@pytest.fixture
def fraud_headers():
    return TEST_USERS["fraud_headers"]


@pytest.fixture
def tenant_headers():
    return TEST_USERS["tenant_headers"]


@pytest.fixture
def landlord_headers():
    return TEST_USERS["landlord_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
