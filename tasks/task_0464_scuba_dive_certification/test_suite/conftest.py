"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle; tests assume the server is
already running and reachable at API_BASE_URL.
"""
import pytest
from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    make_shop_admin_headers, make_instructor_headers, make_diver_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["shop_admin_headers"]


@pytest.fixture
def instructor_headers():
    return TEST_USERS["instructor_headers"]


@pytest.fixture
def diver_headers():
    return TEST_USERS["diver_headers"]


@pytest.fixture
def make_admin():
    return make_shop_admin_headers


@pytest.fixture
def make_instructor():
    return make_instructor_headers


@pytest.fixture
def make_diver():
    return make_diver_headers
