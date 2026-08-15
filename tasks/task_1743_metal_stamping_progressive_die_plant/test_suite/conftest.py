"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def plant_admin_headers():
    return TEST_USERS["plant_admin_headers"]


@pytest.fixture
def process_engineer_headers():
    return TEST_USERS["process_engineer_headers"]


@pytest.fixture
def toolroom_manager_headers():
    return TEST_USERS["toolroom_manager_headers"]


@pytest.fixture
def setup_lead_headers():
    return TEST_USERS["setup_lead_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def press_operator_headers():
    return TEST_USERS["press_operator_headers"]


@pytest.fixture
def quality_engineer_headers():
    return TEST_USERS["quality_engineer_headers"]


@pytest.fixture
def shipping_clerk_headers():
    return TEST_USERS["shipping_clerk_headers"]


@pytest.fixture
def cost_analyst_headers():
    return TEST_USERS["cost_analyst_headers"]
