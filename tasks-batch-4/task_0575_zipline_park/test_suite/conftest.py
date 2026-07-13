"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop/health) is owned by prd-bench-local-runner; these
fixtures only surface the shared API client and role headers. The runner restarts
the server (empty DB) before every individual test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def guide_headers():
    return TEST_USERS["guide_headers"]
