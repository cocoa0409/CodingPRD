"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH so test_helpers is importable, and manages the
server lifecycle (restarting it before every test against an empty database).
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def pm_headers():
    """PropertyManager (opaque role) — shared constant is canonical."""
    return TEST_USERS["property_manager_headers"]


@pytest.fixture
def corporate_admin_headers():
    """CorporateAdmin fallback headers (non-ownership tests only)."""
    return TEST_USERS["corporate_admin_headers"]


@pytest.fixture
def employee_headers():
    """Employee fallback headers (non-ownership tests only)."""
    return TEST_USERS["employee_headers"]
