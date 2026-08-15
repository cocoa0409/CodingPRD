"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def forwarder_ops_headers():
    return TEST_USERS["forwarder_ops_headers"]


@pytest.fixture
def capacity_planner_headers():
    return TEST_USERS["capacity_planner_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def customs_broker_headers():
    return TEST_USERS["customs_broker_headers"]


@pytest.fixture
def pricing_manager_headers():
    return TEST_USERS["pricing_manager_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]
