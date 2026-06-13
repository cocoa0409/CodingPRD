"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_admin_headers,
    make_driver_headers,
    make_parent_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def driver_headers():
    """Shared-constant Driver headers (non-ownership tests only)."""
    return TEST_USERS["driver_headers"]


@pytest.fixture
def parent_headers():
    """Parent par-1 headers."""
    return TEST_USERS["parent_headers"]


@pytest.fixture
def parent_2_headers():
    """Parent par-2 headers (non-owner)."""
    return TEST_USERS["parent_2_headers"]


@pytest.fixture
def make_driver():
    return make_driver_headers


@pytest.fixture
def make_parent():
    return make_parent_headers


@pytest.fixture
def make_admin():
    return make_admin_headers
