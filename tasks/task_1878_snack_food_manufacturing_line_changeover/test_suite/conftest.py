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
def line_operator_headers():
    return TEST_USERS["line_operator_headers"]


@pytest.fixture
def quality_tech_headers():
    return TEST_USERS["quality_tech_headers"]


@pytest.fixture
def route_planner_headers():
    return TEST_USERS["route_planner_headers"]


@pytest.fixture
def coman_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["coman_headers"]
