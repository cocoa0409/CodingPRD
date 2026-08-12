"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS
from test_helpers.fixtures import reset_clock_cache


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_helper_clock_cache():
    """Per-test reset of the fixture module's monotonic-clock cache: the runner
    reboots the server (fresh logical clock) before every test, so the cache
    must not carry a prior test's high-water mark into this one."""
    reset_clock_cache()
    yield


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def sales_rep_headers():
    return TEST_USERS["sales_rep_headers"]


@pytest.fixture
def assessor_headers():
    return TEST_USERS["assessor_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def funding_officer_headers():
    return TEST_USERS["funding_officer_headers"]


@pytest.fixture
def install_coordinator_headers():
    return TEST_USERS["install_coordinator_headers"]


@pytest.fixture
def inventory_manager_headers():
    return TEST_USERS["inventory_manager_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]
