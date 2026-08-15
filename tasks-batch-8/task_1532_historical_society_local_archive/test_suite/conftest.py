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
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def archivist_headers():
    return TEST_USERS["archivist_headers"]


@pytest.fixture
def reading_room_staff_headers():
    return TEST_USERS["reading_room_staff_headers"]


@pytest.fixture
def board_officer_headers():
    return TEST_USERS["board_officer_headers"]


@pytest.fixture
def volunteer_coordinator_headers():
    return TEST_USERS["volunteer_coordinator_headers"]


@pytest.fixture
def volunteer_headers():
    return TEST_USERS["volunteer_headers"]


@pytest.fixture
def researcher_headers():
    return TEST_USERS["researcher_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]
