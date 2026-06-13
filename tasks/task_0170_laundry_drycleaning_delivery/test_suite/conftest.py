"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, and starts a fresh
server before every test (empty database). Fixtures here are thin bridges.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def dispatch_headers():
    return TEST_USERS["dispatch_headers"]


@pytest.fixture
def plant_headers():
    return TEST_USERS["plant_headers"]


@pytest.fixture
def adjuster_headers():
    return TEST_USERS["adjuster_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
