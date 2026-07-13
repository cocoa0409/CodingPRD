"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, injects API_BASE_URL,
and restarts the server (empty DB, clock reset to 2026-03-01T00:00:00Z) before
every individual test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["public_works_admin_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["route_dispatcher_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["signage_inspector_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["enforcement_officer_headers"]


@pytest.fixture
def resident_headers():
    return TEST_USERS["resident_headers"]
