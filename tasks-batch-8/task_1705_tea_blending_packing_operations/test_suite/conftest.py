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
def procurement_lead_headers():
    return TEST_USERS["procurement_lead_headers"]


@pytest.fixture
def sensory_grader_headers():
    return TEST_USERS["sensory_grader_headers"]


@pytest.fixture
def qa_lab_analyst_headers():
    return TEST_USERS["qa_lab_analyst_headers"]


@pytest.fixture
def qa_manager_headers():
    return TEST_USERS["qa_manager_headers"]


@pytest.fixture
def blend_master_headers():
    return TEST_USERS["blend_master_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def account_manager_headers():
    return TEST_USERS["account_manager_headers"]


@pytest.fixture
def certification_officer_headers():
    return TEST_USERS["certification_officer_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
