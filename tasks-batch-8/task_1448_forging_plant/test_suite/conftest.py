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
def saw_operator_headers():
    return TEST_USERS["saw_operator_headers"]


@pytest.fixture
def furnace_operator_headers():
    return TEST_USERS["furnace_operator_headers"]


@pytest.fixture
def forge_operator_headers():
    return TEST_USERS["forge_operator_headers"]


@pytest.fixture
def die_tech_headers():
    return TEST_USERS["die_tech_headers"]


@pytest.fixture
def quality_engineer_headers():
    return TEST_USERS["quality_engineer_headers"]


@pytest.fixture
def quality_engineer_2_headers():
    return TEST_USERS["quality_engineer_2_headers"]


@pytest.fixture
def sales_planner_headers():
    return TEST_USERS["sales_planner_headers"]
