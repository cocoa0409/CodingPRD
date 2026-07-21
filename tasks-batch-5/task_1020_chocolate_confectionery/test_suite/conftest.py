"""Pytest fixtures exposing test_helpers infrastructure.

The runner injects API_BASE_URL into the environment and adds the project root
to PYTHONPATH before invoking pytest, so test_helpers imports cleanly. The
server is restarted before every test, so each test begins against an empty DB.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def sales_manager_headers():
    return TEST_USERS["sales_manager_headers"]


@pytest.fixture
def production_manager_headers():
    return TEST_USERS["production_manager_headers"]


@pytest.fixture
def customer_headers_fallback():
    """Fallback Customer headers; safe only for tests where the rejection is a
    forbidden-role check (the literal X-User-ID need not match a real id)."""
    return TEST_USERS["customer_headers"]
