"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH so test_helpers is importable, sets API_BASE_URL,
and restarts the server before each test (empty DB per test).
"""
import pytest
from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    make_administrator_headers, make_operator_headers,
    make_licensee_headers, make_rightsholder_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["administrator_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def licensee_headers():
    return TEST_USERS["licensee_headers"]


@pytest.fixture
def rightsholder_headers():
    return TEST_USERS["rightsholder_headers"]


@pytest.fixture
def make_licensee():
    return make_licensee_headers


@pytest.fixture
def make_rightsholder():
    return make_rightsholder_headers
