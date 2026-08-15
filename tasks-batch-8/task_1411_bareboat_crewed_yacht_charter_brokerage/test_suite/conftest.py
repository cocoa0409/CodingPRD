"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture(autouse=True)
def _fresh_connection_pool():
    """Drop pooled keep-alive connections before every test.

    The harness kills and restarts the API server before each test
    (per-test-server isolation). A pooled connection to the just-killed
    server would surface as ECONNRESET on the next request, so each test
    opens a fresh connection to the fresh server.
    """
    api_client.session.close()
    yield


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
