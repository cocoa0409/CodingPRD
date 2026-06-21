"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` imports cleanly, and manages the
server lifecycle (it restarts the server before every test). These fixtures are
thin wrappers exposing the shared API client and role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def vendor_headers():
    """Shared Vendor constant. Use only for non-ownership Vendor probes;
    ownership-gated calls must use make_vendor_headers(vendor_id)."""
    return TEST_USERS["vendor_headers"]
