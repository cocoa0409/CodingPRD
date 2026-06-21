"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle (start/stop/restart before each test) and
PYTHONPATH, so test_helpers is importable directly.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def shop_manager_headers():
    return TEST_USERS["shop_manager_headers"]


@pytest.fixture
def designer_headers():
    return TEST_USERS["designer_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def surveyor_headers():
    return TEST_USERS["surveyor_headers"]


@pytest.fixture
def permit_clerk_headers():
    return TEST_USERS["permit_clerk_headers"]
