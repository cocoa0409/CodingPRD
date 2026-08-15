"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture(autouse=True)
def _drop_stale_keepalive_connections():
    """Per-test-server isolation SIGKILLs and reboots the API server on the same
    port before every test. The shared client's keep-alive pool can otherwise
    hand the first request of the next test a dead connection, which surfaces
    as `Remote end closed connection without response` on non-idempotent POSTs
    (urllib3 does not retry those). Closing the session empties the pool, so
    the next request always dials a fresh connection to the fresh server."""
    api_client.session.close()
    yield


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def operator2_headers():
    return TEST_USERS["operator2_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def supervisor2_headers():
    return TEST_USERS["supervisor2_headers"]


@pytest.fixture
def liaison_headers():
    return TEST_USERS["liaison_headers"]
