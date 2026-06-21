"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH (so `test_helpers` is importable) and the server
lifecycle (restart before every test). These fixtures only wire the client and
role headers into pytest.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def manager_headers():
    return TEST_USERS["club_manager_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
