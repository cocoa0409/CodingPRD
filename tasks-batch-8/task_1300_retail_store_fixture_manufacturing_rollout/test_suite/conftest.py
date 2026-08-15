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
def program_manager_headers():
    return TEST_USERS["program_manager_headers"]


@pytest.fixture
def fixture_engineer_headers():
    return TEST_USERS["fixture_engineer_headers"]


@pytest.fixture
def config_coordinator_headers():
    return TEST_USERS["config_coordinator_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def warehouse_lead_headers():
    return TEST_USERS["warehouse_lead_headers"]


@pytest.fixture
def install_crew_lead_headers():
    return TEST_USERS["install_crew_lead_headers"]


@pytest.fixture
def hotline_agent_headers():
    return TEST_USERS["hotline_agent_headers"]


@pytest.fixture
def store_manager_headers():
    return TEST_USERS["store_manager_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
