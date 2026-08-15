"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def plant_admin_headers():
    return TEST_USERS["plant_admin"]


@pytest.fixture
def process_engineer_headers():
    return TEST_USERS["process_engineer"]


@pytest.fixture
def quality_technician_headers():
    return TEST_USERS["quality_technician"]


@pytest.fixture
def production_scheduler_headers():
    return TEST_USERS["production_scheduler"]


@pytest.fixture
def logistics_coordinator_headers():
    return TEST_USERS["logistics_coordinator"]
