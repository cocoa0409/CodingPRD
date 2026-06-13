"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH (so `test_helpers` is importable) and the server
lifecycle (restarting it before every test against an empty database).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def owner_headers():
    return TEST_USERS["owner_headers"]
