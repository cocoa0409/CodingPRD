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
def escrow_officer_headers() -> dict:
    """Shared EscrowOfficer headers carrying a placeholder X-User-ID.

    Safe for non-ownership tests (401/403/404). For ownership-gated
    success paths, callers must use ``make_escrow_officer_headers(user_id)``
    after registering the User row.
    """
    return TEST_USERS["escrow_officer_headers"]


@pytest.fixture
def title_agent_headers() -> dict:
    return TEST_USERS["title_agent_headers"]


@pytest.fixture
def compliance_officer_headers() -> dict:
    return TEST_USERS["compliance_officer_headers"]
