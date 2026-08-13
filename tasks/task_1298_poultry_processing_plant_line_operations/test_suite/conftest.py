"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def plant_manager_headers():
    return TEST_USERS["plant_manager_headers"]


@pytest.fixture
def shift_supervisor_headers():
    return TEST_USERS["shift_supervisor_headers"]


@pytest.fixture
def receiving_clerk_headers():
    return TEST_USERS["receiving_clerk_headers"]


@pytest.fixture
def line_operator_headers():
    return TEST_USERS["line_operator_headers"]


@pytest.fixture
def qa_technician_headers():
    return TEST_USERS["qa_technician_headers"]


@pytest.fixture
def sanitation_lead_headers():
    return TEST_USERS["sanitation_lead_headers"]


@pytest.fixture
def usda_inspector_headers():
    return TEST_USERS["usda_inspector_headers"]


@pytest.fixture
def order_planner_headers():
    return TEST_USERS["order_planner_headers"]
