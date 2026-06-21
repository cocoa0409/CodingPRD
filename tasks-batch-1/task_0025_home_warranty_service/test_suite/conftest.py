"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; each test starts against a
freshly-restarted (empty-database) API per the per-test-server isolation contract.
"""
import pytest

from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def admin_headers() -> dict:
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def dispatcher_headers() -> dict:
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def technician_headers() -> dict:
    return TEST_USERS["technician_headers"]


@pytest.fixture
def customer_headers() -> dict:
    """Generic Customer headers (fake user-id). Use only for non-ownership tests
    (e.g., 401/404 paths)."""
    return TEST_USERS["customer_headers"]


@pytest.fixture
def anonymous_headers() -> dict:
    return TEST_USERS["anonymous_headers"]
