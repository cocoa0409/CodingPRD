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
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def case_manager_headers() -> dict:
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def billing_clerk_headers() -> dict:
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def va_coordinator_headers() -> dict:
    return TEST_USERS["va_coordinator_headers"]


@pytest.fixture
def therapist_headers() -> dict:
    """Generic Therapist headers (fake user-id). Use only for non-ownership tests
    (e.g., 401/404 paths). Real ownership-gated calls must use
    make_therapist_headers(therapist["id"])."""
    return TEST_USERS["therapist_headers"]
