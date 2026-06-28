"""Pytest fixtures exposing test_helpers infrastructure.

The runner handles PYTHONPATH so test_helpers is importable without sys.path hacks.
Each test runs against a freshly-restarted (empty) server.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def attorney_headers():
    return TEST_USERS["attorney_headers"]
