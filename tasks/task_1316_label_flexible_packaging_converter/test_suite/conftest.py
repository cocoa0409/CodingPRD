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
    keep-alive reuse *within* a test — which keeps connection churn (and
    therefore loopback TIME_WAIT pressure) low during parallel sweeps.
    """
    api_client.session.close()
    yield


@pytest.fixture
def estimator_headers():
    return TEST_USERS["estimator_headers"]


@pytest.fixture
def prepress_operator_headers():
    return TEST_USERS["prepress_operator_headers"]


@pytest.fixture
def press_operator_headers():
    return TEST_USERS["press_operator_headers"]


@pytest.fixture
def quality_manager_headers():
    return TEST_USERS["quality_manager_headers"]
