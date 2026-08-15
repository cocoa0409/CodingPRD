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
    opens a fresh connection to the fresh server, while still allowing
    keep-alive reuse *within* a test.
    """
    api_client.session.close()
    yield


@pytest.fixture
def service_writer_headers():
    return TEST_USERS["service_writer_headers"]


@pytest.fixture
def yard_manager_headers():
    return TEST_USERS["yard_manager_headers"]


@pytest.fixture
def environmental_officer_headers():
    return TEST_USERS["environmental_officer_headers"]


@pytest.fixture
def accountant_headers():
    return TEST_USERS["accountant_headers"]


@pytest.fixture
def owner_headers():
    return TEST_USERS["owner_headers"]
