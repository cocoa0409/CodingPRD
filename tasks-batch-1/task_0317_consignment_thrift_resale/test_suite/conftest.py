"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH (so `test_helpers` imports cleanly) and the server
lifecycle (restarting it before every test). These fixtures just wire the
shared api client and role headers into pytest.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def store_admin_headers():
    return TEST_USERS["store_admin_headers"]


@pytest.fixture
def intake_grader_headers():
    return TEST_USERS["intake_grader_headers"]


@pytest.fixture
def authenticator_headers():
    return TEST_USERS["authenticator_headers"]


@pytest.fixture
def cashier_clerk_headers():
    return TEST_USERS["cashier_clerk_headers"]


@pytest.fixture
def settlement_manager_headers():
    return TEST_USERS["settlement_manager_headers"]
