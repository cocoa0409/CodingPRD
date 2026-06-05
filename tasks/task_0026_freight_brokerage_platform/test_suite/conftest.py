"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; each pytest test starts
against a freshly-restarted (empty-database) API per the per-test-server
isolation contract. The conftest just wires up the role headers.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def broker_ops_headers() -> dict:
    """Opaque BrokerOps headers — safe to reuse across tests (PRD §2.1)."""
    return TEST_USERS["broker_ops_headers"]


@pytest.fixture
def shipper_headers() -> dict:
    """Generic Shipper headers (placeholder user-id). Use only for tests that
    do NOT depend on ownership matching (401/403/404 paths)."""
    return TEST_USERS["shipper_headers"]


@pytest.fixture
def carrier_headers() -> dict:
    """Generic Carrier headers (placeholder user-id). Same caveat as
    `shipper_headers`."""
    return TEST_USERS["carrier_headers"]


@pytest.fixture
def anonymous_headers() -> dict:
    """Empty header dict for unauthenticated requests."""
    return TEST_USERS["anonymous_headers"]
