"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def menu_planner_headers():
    return TEST_USERS["menu_planner_headers"]


@pytest.fixture
def nutrition_director_headers():
    return TEST_USERS["nutrition_director_headers"]


@pytest.fixture
def cafeteria_manager_headers():
    return TEST_USERS["cafeteria_manager_headers"]


@pytest.fixture
def pos_clerk_headers():
    return TEST_USERS["pos_clerk_headers"]
