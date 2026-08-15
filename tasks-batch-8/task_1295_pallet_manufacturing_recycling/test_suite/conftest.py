"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def procurement_manager_headers():
    return TEST_USERS["procurement_manager_headers"]


@pytest.fixture
def yard_supervisor_headers():
    return TEST_USERS["yard_supervisor_headers"]


@pytest.fixture
def heat_treat_operator_headers():
    return TEST_USERS["heat_treat_operator_headers"]


@pytest.fixture
def sales_rep_headers():
    return TEST_USERS["sales_rep_headers"]


@pytest.fixture
def fleet_planner_headers():
    return TEST_USERS["fleet_planner_headers"]


@pytest.fixture
def plant_manager_headers():
    return TEST_USERS["plant_manager_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
