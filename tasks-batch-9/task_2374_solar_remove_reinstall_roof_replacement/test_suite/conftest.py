"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(autouse=True)
def _drop_stale_keepalive_connections():
    """Discard pooled sockets left over from the previous test's server process.

    The harness restarts the API server on the same port before every test
    (``--isolation per-test-server``), but ``test_helpers.api_client`` is a
    module-level client holding one ``requests.Session``. Its keep-alive pool
    therefore still contains connections to the process the harness has just
    killed; reusing one surfaces as ``RemoteDisconnected`` /
    ``IncompleteRead`` on the first request a test issues. Closing the session
    only clears the connection pools -- the session stays usable -- so every
    test opens fresh connections to the freshly booted server.
    """
    api_client.session.close()
    yield


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the harness."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def solar_contractor_headers():
    return TEST_USERS["solar_contractor_headers"]


@pytest.fixture
def roofing_contractor_headers():
    return TEST_USERS["roofing_contractor_headers"]


@pytest.fixture
def solar_owner_headers():
    return TEST_USERS["solar_owner_headers"]


@pytest.fixture
def system_owner_headers():
    return TEST_USERS["system_owner_headers"]


@pytest.fixture
def ahj_inspector_headers():
    return TEST_USERS["ahj_inspector_headers"]
