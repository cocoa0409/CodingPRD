"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, injects API_BASE_URL,
and restarts the server before every test (empty DB, logical clock reset to
2026-05-01T00:00:00Z).
"""
import pytest
from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    make_treasurer_headers, make_cashier_headers, make_collections_headers,
    make_relief_headers, make_taxpayer_headers, anonymous_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def treasurer_headers():
    return TEST_USERS["treasurer_headers"]


@pytest.fixture
def cashier_headers():
    return TEST_USERS["cashier_headers"]


@pytest.fixture
def collections_headers():
    return TEST_USERS["collections_headers"]


@pytest.fixture
def relief_headers():
    return TEST_USERS["relief_headers"]


@pytest.fixture
def anon_headers():
    return anonymous_headers()
