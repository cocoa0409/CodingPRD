"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture(autouse=True)
def _fresh_connection_pool():
    """Drop pooled keep-alive connections before every test.

    The harness kills and restarts the API server before each test
    (per-test-server isolation). A pooled connection to the just-killed
    server surfaces as ECONNRESET on the next request. Emptying the pool
    guarantees each test opens a fresh connection to the fresh server.
    """
    api_client.session.close()
    yield


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def accountant_headers():
    return TEST_USERS["accountant_headers"]


@pytest.fixture
def producer_headers():
    return TEST_USERS["producer_headers"]
