"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, sets API_BASE_URL,
and restarts the server (fresh empty database) before every individual test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def ops_headers():
    """OperationsManager (opaque role): shared constant is canonical."""
    return TEST_USERS["ops_manager_headers"]


@pytest.fixture
def client_headers():
    """Shared Client constant — for NON-ownership probes only. Ownership-gated
    calls must build per-client headers via make_client_headers(client_id)."""
    return TEST_USERS["client_headers"]


@pytest.fixture
def barista_headers():
    """Shared Barista constant — for NON-ownership probes only. Ownership-gated
    calls must build per-barista headers via make_barista_headers(barista_id)."""
    return TEST_USERS["barista_headers"]
