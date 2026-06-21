"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; each test starts against
a freshly-restarted (empty-database) API per the per-test-server isolation
contract.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def admin_headers() -> dict:
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def ops_headers() -> dict:
    return TEST_USERS["rewards_ops_headers"]


@pytest.fixture
def cardholder_headers() -> dict:
    """Generic Cardholder headers with a placeholder user-id.

    Use only for non-ownership negative paths (401/403/404). Real ownership-gated
    calls must use make_cardholder_headers(account["id"])."""
    return TEST_USERS["cardholder_headers"]
