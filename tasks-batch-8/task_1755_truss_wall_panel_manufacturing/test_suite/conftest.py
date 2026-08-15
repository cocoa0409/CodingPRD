"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def plant_manager_headers():
    return TEST_USERS["plant_manager_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def inventory_manager_headers():
    return TEST_USERS["inventory_manager_headers"]


@pytest.fixture
def shop_floor_lead_headers():
    return TEST_USERS["shop_floor_lead_headers"]


@pytest.fixture
def shipping_coordinator_headers():
    return TEST_USERS["shipping_coordinator_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def design_engineer_headers():
    return TEST_USERS["design_engineer_headers"]


@pytest.fixture
def customer_contact_headers():
    return TEST_USERS["customer_contact_headers"]
