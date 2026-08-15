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

    The harness restarts the API server before each test; a pooled
    connection to the just-killed server would surface as ECONNRESET on the
    next request. Emptying the pool guarantees a fresh connection to the
    fresh server while keeping keep-alive reuse within a test.
    """
    api_client.session.close()
    yield


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def registrar_clerk_headers():
    return TEST_USERS["registrar_clerk_headers"]


@pytest.fixture
def financial_aid_officer_headers():
    return TEST_USERS["financial_aid_officer_headers"]


@pytest.fixture
def bursar_clerk_headers():
    return TEST_USERS["bursar_clerk_headers"]


@pytest.fixture
def student_headers():
    return TEST_USERS["student_headers"]
