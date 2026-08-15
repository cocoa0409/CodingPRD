"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns the server lifecycle and restarts the API before every test,
so each test starts against an empty database with the logical clock at its
fixed default. All state is built per-test via test_helpers factories/fixtures.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def manager_headers() -> dict:
    return TEST_USERS["manager_headers"]


@pytest.fixture
def dispatcher_headers() -> dict:
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def resident_headers() -> dict:
    return TEST_USERS["resident_headers"]


@pytest.fixture
def technician_headers() -> dict:
    return TEST_USERS["technician_headers"]


@pytest.fixture
def vendor_headers() -> dict:
    return TEST_USERS["vendor_headers"]
