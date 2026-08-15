"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def operations_manager_headers():
    return TEST_USERS["operations_manager_headers"]


@pytest.fixture
def dock_buyer_headers():
    return TEST_USERS["dock_buyer_headers"]


@pytest.fixture
def grading_inspector_headers():
    return TEST_USERS["grading_inspector_headers"]


@pytest.fixture
def inventory_planner_headers():
    return TEST_USERS["inventory_planner_headers"]


@pytest.fixture
def logistics_coordinator_headers():
    return TEST_USERS["logistics_coordinator_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def vessel_agent_headers():
    return TEST_USERS["vessel_agent_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
