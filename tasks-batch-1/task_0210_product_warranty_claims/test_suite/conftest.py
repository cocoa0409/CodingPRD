"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; each test starts against a
freshly-restarted (empty-database) API per the per-test-server isolation contract.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def owner_headers() -> dict:
    """Generic (entity-unbound) Owner headers. For ownership-gated tests, use
    make_owner_headers(owner_id) with the real Owner.id instead."""
    return TEST_USERS["owner_headers"]


@pytest.fixture
def warranty_admin_headers() -> dict:
    return TEST_USERS["warranty_admin_headers"]


@pytest.fixture
def claims_processor_headers() -> dict:
    return TEST_USERS["claims_processor_headers"]
