"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def mill_planner_headers():
    return TEST_USERS["mill_planner_headers"]


@pytest.fixture
def spinning_supervisor_headers():
    return TEST_USERS["spinning_supervisor_headers"]


@pytest.fixture
def dye_house_operator_headers():
    return TEST_USERS["dye_house_operator_headers"]


@pytest.fixture
def quality_inspector_headers():
    return TEST_USERS["quality_inspector_headers"]


@pytest.fixture
def customer_service_rep_headers():
    return TEST_USERS["customer_service_rep_headers"]


@pytest.fixture
def mill_admin_headers():
    return TEST_USERS["mill_admin_headers"]
