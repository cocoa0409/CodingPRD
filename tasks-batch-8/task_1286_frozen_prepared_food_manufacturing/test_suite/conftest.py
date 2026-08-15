"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def plant_manager_headers():
    return TEST_USERS["plant_manager_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def line_operator_headers():
    return TEST_USERS["line_operator_headers"]


@pytest.fixture
def qa_technician_headers():
    return TEST_USERS["qa_technician_headers"]


@pytest.fixture
def qa_manager_headers():
    return TEST_USERS["qa_manager_headers"]


@pytest.fixture
def warehouse_lead_headers():
    return TEST_USERS["warehouse_lead_headers"]
