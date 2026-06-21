"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` imports cleanly, and owns the
server lifecycle (restart before every test). These fixtures only wire up the
shared API client and role headers.
"""
import pytest
from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    make_ops_manager_headers, make_cashier_headers, make_guest_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def ops_manager_headers():
    return TEST_USERS["ops_manager_headers"]


@pytest.fixture
def cashier_headers():
    return TEST_USERS["cashier_headers"]


@pytest.fixture
def guest_headers():
    return TEST_USERS["guest_headers"]


@pytest.fixture
def make_ops_headers():
    return make_ops_manager_headers


@pytest.fixture
def make_cashier():
    return make_cashier_headers


@pytest.fixture
def make_guest():
    return make_guest_headers
