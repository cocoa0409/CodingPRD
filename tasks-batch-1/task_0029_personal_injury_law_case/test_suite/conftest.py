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
def anonymous_headers() -> dict:
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def paralegal_headers() -> dict:
    return TEST_USERS["paralegal_headers"]


@pytest.fixture
def attorney_headers() -> dict:
    return TEST_USERS["attorney_headers"]


@pytest.fixture
def managing_partner_headers() -> dict:
    return TEST_USERS["managing_partner_headers"]


@pytest.fixture
def platform_admin_headers() -> dict:
    return TEST_USERS["platform_admin_headers"]
