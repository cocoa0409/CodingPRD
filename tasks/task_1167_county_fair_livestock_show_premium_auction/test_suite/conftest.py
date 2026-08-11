"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle, API_BASE_URL injection and PYTHONPATH; the
client below assumes the server is already reachable.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin"]


@pytest.fixture
def weigh_master_headers():
    return TEST_USERS["weigh_master"]


@pytest.fixture
def show_clerk_headers():
    return TEST_USERS["show_clerk"]


@pytest.fixture
def auctioneer_headers():
    return TEST_USERS["auctioneer"]


@pytest.fixture
def health_inspector_headers():
    return TEST_USERS["health_inspector"]


@pytest.fixture
def treasurer_headers():
    return TEST_USERS["treasurer"]
