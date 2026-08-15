"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def ops_manager_headers():
    return TEST_USERS["ops_manager_headers"]


@pytest.fixture
def ops_manager_b_headers():
    return TEST_USERS["ops_manager_b_headers"]


@pytest.fixture
def tour_manager_headers():
    return TEST_USERS["tour_manager_headers"]


@pytest.fixture
def logistics_headers():
    return TEST_USERS["logistics_headers"]


@pytest.fixture
def warehouse_tech_headers():
    return TEST_USERS["warehouse_tech_headers"]


@pytest.fixture
def warehouse_tech_b_headers():
    return TEST_USERS["warehouse_tech_b_headers"]
