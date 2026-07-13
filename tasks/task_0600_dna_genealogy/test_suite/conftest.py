"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import api_client, ApiClient, TEST_USERS, NO_AUTH_HEADERS


@pytest.fixture(autouse=True)
def _drop_stale_pooled_connections():
    """Force a fresh TCP connection at the start of every test.

    The runner restarts the API server process (via `start.sh`) before every test, but
    `api_client` is a module-level singleton whose `requests.Session` pools keep-alive
    connections. Those pooled sockets point at the *previous* server process, which is
    already dead by the time the next test runs. Writing a request onto one of them fails
    at the transport layer — `requests` raises ConnectionError(BadStatusLine(...)) — and
    since `HTTPAdapter` defaults to `max_retries=0`, nothing retries it.

    `Session.close()` clears the adapters' connection pools without invalidating the
    session; the next request dials a new connection to the freshly booted server. This is
    a client-lifecycle correction, not a retry wrapper: a genuine server-side abort still
    fails the test.
    """
    api_client.session.close()
    yield


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the test runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """PlatformAdmin — opaque identity."""
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def lab_headers():
    """LabTechnician — opaque identity."""
    return TEST_USERS["lab_technician_headers"]


@pytest.fixture
def officer_headers():
    """PrivacyOfficer — opaque identity, recorded verbatim in reviewed_by."""
    return TEST_USERS["privacy_officer_headers"]


@pytest.fixture
def customer_headers():
    """Customer role with a placeholder identity. Only for calls that never reach an
    ownership check; ownership-gated calls must use make_customer_headers(<real id>)."""
    return TEST_USERS["customer_headers"]


@pytest.fixture
def no_auth_headers():
    """Headers carrying neither X-User-ID nor X-User-Role."""
    return NO_AUTH_HEADERS
