"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; each test starts
against a freshly-restarted (empty-database) API per the per-test-server
isolation contract.
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
def harbor_master_headers() -> dict:
    return TEST_USERS["harbor_master_headers"]


@pytest.fixture
def marina_staff_headers() -> dict:
    return TEST_USERS["marina_staff_headers"]


@pytest.fixture
def tenant_headers() -> dict:
    """Generic Tenant headers (fake user-id). Use only for non-ownership tests
    (e.g., 401/404 paths). Real ownership-gated calls must use
    make_tenant_headers(tenant["id"])."""
    return TEST_USERS["tenant_headers"]
