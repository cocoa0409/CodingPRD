"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, injects API_BASE_URL,
and restarts the server before every test — these fixtures never touch lifecycle.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def studio_admin_headers():
    return TEST_USERS["studio_admin_headers"]


@pytest.fixture
def designer_headers():
    return TEST_USERS["designer_headers"]


@pytest.fixture
def procurement_coordinator_headers():
    return TEST_USERS["procurement_coordinator_headers"]


@pytest.fixture
def client_headers():
    """Shared Client constant — for non-ownership tests only. Ownership-gated Client
    calls must use make_client_headers(client_id)."""
    return TEST_USERS["client_headers"]
