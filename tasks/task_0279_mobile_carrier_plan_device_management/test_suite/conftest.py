"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, and owns the server
lifecycle (it restarts the API server before every individual test). These
fixtures merely wire the shared client and role headers into pytest.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def carrier_agent_headers():
    return TEST_USERS["carrier_agent_headers"]


@pytest.fixture
def porting_ops_headers():
    return TEST_USERS["porting_ops_headers"]


@pytest.fixture
def billing_system_headers():
    return TEST_USERS["billing_system_headers"]


@pytest.fixture
def subscriber_headers():
    return TEST_USERS["subscriber_headers"]
