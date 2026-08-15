"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def dealer_rep_headers():
    return TEST_USERS["dealer_rep_headers"]


@pytest.fixture
def plant_engineer_headers():
    return TEST_USERS["plant_engineer_headers"]


@pytest.fixture
def production_lead_headers():
    return TEST_USERS["production_lead_headers"]


@pytest.fixture
def shipping_coordinator_headers():
    return TEST_USERS["shipping_coordinator_headers"]


@pytest.fixture
def warranty_adjuster_headers():
    return TEST_USERS["warranty_adjuster_headers"]


@pytest.fixture
def plant_manager_headers():
    return TEST_USERS["plant_manager_headers"]
