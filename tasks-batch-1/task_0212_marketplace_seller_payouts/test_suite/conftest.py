"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle and PYTHONPATH are managed by prd-bench-local-runner; this
file only wires up fixtures.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def seller_headers():
    """Shared Seller header (placeholder id) — only for non-ownership tests."""
    return TEST_USERS["seller_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def finance2_headers():
    return TEST_USERS["finance2_headers"]
