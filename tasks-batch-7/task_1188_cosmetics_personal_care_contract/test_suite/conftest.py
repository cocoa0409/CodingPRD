"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def plant_director_headers():
    return TEST_USERS["plant_director_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def qa_manager_headers():
    return TEST_USERS["qa_manager_headers"]


@pytest.fixture
def qa1_headers():
    return TEST_USERS["qa_manager_1_headers"]


@pytest.fixture
def qa2_headers():
    return TEST_USERS["qa_manager_2_headers"]


@pytest.fixture
def formulation_chemist_headers():
    return TEST_USERS["formulation_chemist_headers"]


@pytest.fixture
def regulatory_affairs_headers():
    return TEST_USERS["regulatory_affairs_headers"]


@pytest.fixture
def customer_rep_headers():
    return TEST_USERS["customer_rep_headers"]
