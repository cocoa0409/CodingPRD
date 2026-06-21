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
    return TEST_USERS["field_office_admin_headers"]


@pytest.fixture
def officer_headers() -> dict:
    return TEST_USERS["officer_headers"]


@pytest.fixture
def applicant_headers() -> dict:
    """Generic Applicant headers (fake user-id). Use only for non-ownership tests
    (e.g., 401/404 paths or assertions that do not depend on ownership matching)."""
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def attorney_headers() -> dict:
    """Generic Attorney headers (fake user-id). Same caveat as applicant_headers."""
    return TEST_USERS["attorney_headers"]


@pytest.fixture
def anonymous_headers() -> dict:
    return TEST_USERS["anonymous_headers"]
