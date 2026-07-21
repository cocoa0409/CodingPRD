"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH so test_helpers is importable, and manages the
server lifecycle (restarting it against an empty database before every test).
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def store_admin_headers():
    """StoreAdmin (opaque role) — shared constant is canonical."""
    return TEST_USERS["store_admin_headers"]


@pytest.fixture
def customer_headers():
    """Customer fallback headers (non-ownership tests only)."""
    return TEST_USERS["customer_headers"]


@pytest.fixture
def commercial_buyer_headers():
    """CommercialBuyer fallback headers (non-ownership tests only)."""
    return TEST_USERS["commercial_buyer_headers"]


@pytest.fixture
def consultant_headers():
    """Consultant fallback headers (non-ownership tests only)."""
    return TEST_USERS["consultant_headers"]
