"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; each test starts against
a freshly-restarted (empty-database) API per the per-test-server isolation
contract.
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
    return TEST_USERS["plan_admin_headers"]


@pytest.fixture
def auditor_headers() -> dict:
    return TEST_USERS["irs_auditor_headers"]


@pytest.fixture
def owner_headers() -> dict:
    """Generic AccountOwner headers with a placeholder user-id.

    Use only for non-ownership negative paths (401/404). Real ownership-gated
    calls must use make_account_owner_headers(owner["id"])."""
    return TEST_USERS["account_owner_headers"]
