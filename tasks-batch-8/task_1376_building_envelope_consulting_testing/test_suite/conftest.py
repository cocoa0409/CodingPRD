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
    server surfaces as ECONNRESET on the next request (POSTs are not
    retried by urllib3). Emptying the pool here guarantees each test
    opens a fresh connection to the fresh server.
    """
    api_client.session.close()
    yield


@pytest.fixture
def principal_headers():
    return TEST_USERS["principal_headers"]


@pytest.fixture
def consultant_headers():
    return TEST_USERS["consultant_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def field_technician_headers():
    return TEST_USERS["field_technician_headers"]


@pytest.fixture
def manufacturer_rep_headers():
    return TEST_USERS["manufacturer_rep_headers"]
