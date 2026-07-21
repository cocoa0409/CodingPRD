"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, injects
API_BASE_URL, and restarts the server (empty DB) before every test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def store_operator_headers():
    return TEST_USERS["store_operator_headers"]


@pytest.fixture
def customer_headers():
    """Shared Customer constant — safe only for non-ownership tests
    (401/403/404 on missing or foreign resources)."""
    return TEST_USERS["customer_headers"]


@pytest.fixture
def practitioner_headers():
    """Shared Practitioner constant — safe only for non-ownership tests."""
    return TEST_USERS["practitioner_headers"]
