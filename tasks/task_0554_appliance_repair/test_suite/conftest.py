"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable and manages the server
lifecycle (restarted before every test), so these fixtures only wire up data.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def service_admin_headers():
    return TEST_USERS["service_admin_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def technician_headers():
    return TEST_USERS["technician_headers"]
