"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, and manages the server
lifecycle (restarting it before every test). Tests never start/stop the server.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """PlatformAdmin (opaque operator identity)."""
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def buyer_headers():
    """Buyer buyer_1 (opaque identity captured as order.buyer_id)."""
    return TEST_USERS["buyer_headers"]
